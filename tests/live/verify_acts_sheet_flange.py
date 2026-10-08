# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The flange-family live sweep act: flange, hem, rip and join-by-bend on the sheet-metal coupon."""

from verify_acts_sheet import (_PART, _RULE, _SEED_BASE, _SHEET_BUILD, _closed_one, _converted,
                               _story_restored, _top_face, _top_handle, _top_match)
from verify_core import _RECALL, _ctx_get, _dwell, _extruded, _measured, _near, _recall, _refused
from verify_acts_feature_edit import (_clean, _definition_restored, _shape_capture,
                                    _shape_changed, _shape_restored, _roll_landed,
                                    _draft_face_identity_args, _draft_face_identity_check)

_RIP_BOX = "SM Sweep Rip Box"
_RIP_BASE = "SM Sweep Rip Box Base"
_RIP_SEED = "SM Sweep Rip Seed"
_JOIN = "SM Sweep Join"
_JOIN_SEED = "SM Sweep Join Seed"
_JOIN_A = "SM Sweep Join Plate A"
_JOIN_A_NOTCH = "SM Sweep Join Plate A Notch"
_JOIN_B = "SM Sweep Join Plate B"
_BASE_KIND_PROFILE = "SM Sweep Base Kind Profile"
_JOIN_E_BASE = "SM Sweep Join Plate E"
_JOIN_F_BASE = "SM Sweep Join Plate F"
_OBLIQUE = "SM Sweep Oblique Flange"
_OBLIQUE_HINGE = "SM Sweep Oblique Hinge"
_OBLIQUE_PLANE = "SM Sweep Oblique Plane"
_OBLIQUE_PROFILE = "SM Sweep Oblique Profile"


def _edge_match(p, x=None, y=None, z=None, length=None, tol=0.1):
    """Find one line_edge matching every given fixed coordinate and length, or None."""
    matches = []
    for m in p.get("matches") or []:
        if m.get("kind") != "line_edge":
            continue
        pos = m.get("position") or [None, None, None]
        if x is not None and not _near(pos[0], x, tol):
            continue
        if y is not None and not _near(pos[1], y, tol):
            continue
        if z is not None and not _near(pos[2], z, tol):
            continue
        if length is not None and not _near(m.get("length"), length, tol):
            continue
        matches.append(m)
    return matches[0] if len(matches) == 1 else None


def _one_edge(label, **kw):
    def check(p):
        m = _edge_match(p, **kw)
        return _measured(label, {"match": m, "count": len(p.get("matches") or [])},
                         m is not None and bool(m.get("handle")))
    return check


def _edge_handle(**kw):
    return lambda p: _edge_match(p, **kw)["handle"]


def _bend_boundary_match(p):
    """The line where the height-20 flange's inner bend cylinder (radius 2 about x=80, z=3.5) meets
    the wall's inner face: at x=82, z=3.5, the full 40 mm width."""
    return _edge_match(p, x=82, z=3.5, length=40)


def _bend_boundary_check(p):
    m = _bend_boundary_match(p)
    return _measured("flange bend-to-plane boundary line", {"match": m, "count": len(p.get("matches") or [])},
                     m is not None and bool(m.get("handle")))


def _bend_boundary_handle(p):
    return _bend_boundary_match(p)["handle"]


def _flange_created(edge_count=1, flat_present=False):
    """Require a landed native edge flange with its bend faces up two per edge."""
    def check(p):
        before = p.get("bend_faces_before")
        want = None if before is None else before + 2 * edge_count
        return _measured("flange landed", {"kind": p.get("kind"),
                         "bend_faces": (p.get("bend_faces_before"), p.get("bend_faces_after"))},
                         p.get("created") is True and p.get("kind") == "edge"
                         and p.get("bend_faces_after") == want
                         and (p.get("flat_pattern") or {}).get("present") is flat_present)
    return check


def _base_body_unfolded(bend_count):
    """Require the base-flange body's all_bends unfold to flatten exactly its own known bends."""
    def check(p):
        return _measured("base-flange body unfolded flat",
                         {"bend_count_unfolded": p.get("bend_count_unfolded"), "faces_moved": p.get("faces_moved")},
                         p.get("created") is True and p.get("all_bends") is True
                         and p.get("bend_count_unfolded") == bend_count
                         and (p.get("faces_moved") or 0) > 0)
    return check


def _base_body_flat(p):
    """Require the base-flange body's overall z extent to read the sheet thickness once flat."""
    return _measured("base-flange body flat after unfold", {"z_mm": p.get("z")}, _near(p.get("z"), 1.5, 0.01))


def _base_body_refolded(p):
    """Require the refold to land on the base-flange body's unfold."""
    return _measured("base-flange body refolded", p, p.get("created") is True)


def _base_body_refolded_extent(p):
    """Require the base-flange body's overall z extent to read its pre-unfold folded height again."""
    return _measured("base-flange body back to folded", {"z_mm": p.get("z")}, _near(p.get("z"), 10.0, 0.3))


def _envelope(label, **want_mm):
    """Pin exact min/max_point mm coordinates read by model_inspect(include=['default'])."""
    def check(p):
        lo, hi = p.get("min_point") or {}, p.get("max_point") or {}
        got = {"min_" + a: lo.get(a) for a in "xyz"}
        got.update({"max_" + a: hi.get(a) for a in "xyz"})
        ok_ = all(_near(got.get(k), v, 0.1) for k, v in want_mm.items())
        return _measured(label, {"got": got, "want": want_mm}, ok_)
    return check


_flange1_envelope = _envelope("flange 1 envelope", max_x=83.5, max_z=20.0)
_flange2_envelope = _envelope("flange 2 envelope", min_x=-3.5, max_z=20.0)
_inner_flange_envelope = _envelope("inner-height flange envelope", min_y=-3.5)
_flip_flange_envelope = _envelope("flip flange envelope", min_z=-8.5)


def _base_flange_created(p):
    """Require a kind='base' flange to add one body under the active component's own rule."""
    return _measured("base flange landed", {"bodies": (p.get("bodies_before"), p.get("bodies_after")),
                     "thickness_mm": p.get("thickness_mm"), "rule": p.get("rule")},
                     p.get("created") is True and p.get("kind") == "base"
                     and isinstance(p.get("bodies_before"), int) and isinstance(p.get("bodies_after"), int)
                     and p["bodies_after"] == p["bodies_before"] + 1
                     and _near(p.get("thickness_mm"), 1.5, 0.01)
                     # a convert renames the component's rule copy "<name> (Convert)"
                     and str(p.get("rule")).startswith(_RULE))


def _two_edge_tips_check(p):
    """Require both edges' own outer tip corners from one two-edge flange call (the rim bulges R+T=3.5 mm)."""
    tips = {"y0_x200": _vertex_near(p, 200, -3.5, 10.0, 0.3), "y0_x240": _vertex_near(p, 240, -3.5, 10.0, 0.3),
            "y20_x200": _vertex_near(p, 200, 23.5, 10.0, 0.3), "y20_x240": _vertex_near(p, 240, 23.5, 10.0, 0.3)}
    return _measured("two-edge flange outer tips", {"count": len(p.get("matches") or []), **tips},
                     all(v is not None for v in tips.values()))


def _blank_extent(p):
    """Read the flat blank's own bbox size before any flange lands."""
    x, y = p.get("x"), p.get("y")
    return _measured("flat blank extent before flanging", {"x_mm": x, "y_mm": y, "z_mm": p.get("z")},
                     _near(x, 80, 0.05) and _near(y, 40, 0.05))


def _hem_created(kind, faces_delta=2):
    """Require a landed hem of the requested kind with its bend faces and grown volume."""
    def check(p):
        return _measured("hem landed", {"kind": p.get("kind"),
                         "bend_faces": (p.get("bend_faces_before"), p.get("bend_faces_after")),
                         "volume": (p.get("volume_before_cm3"), p.get("volume_after_cm3"))},
                         p.get("created") is True and p.get("kind") == kind
                         and isinstance(p.get("bend_faces_before"), int)
                         and isinstance(p.get("bend_faces_after"), int)
                         and p["bend_faces_after"] == p["bend_faces_before"] + faces_delta
                         and isinstance(p.get("volume_before_cm3"), (int, float))
                         and isinstance(p.get("volume_after_cm3"), (int, float))
                         and p["volume_after_cm3"] > p["volume_before_cm3"])
    return check


def _features_row(p, component):
    rows = ((p.get("features") or {}).get("components")) or []
    matches = [r for r in rows if r.get("component") == component]
    return matches[0] if len(matches) == 1 else None


def _flange_family_census(p):
    row = _features_row(p, _PART)
    hems = (row or {}).get("hems") or []
    flat = (row or {}).get("flat_pattern") or {}
    return _measured("flange family feature census", {"row": row},
                     row is not None and row.get("folds") == 0 and row.get("flanges") == 6
                     and len(hems) == 1 and hems[0].get("kind") == "flat" and row.get("rips") == 0
                     and row.get("joins") == 0 and flat.get("present") is False)


def _flange_flat_created(p):
    return _measured("flange family flat pattern", {"created": p.get("created"),
                     "is_solid": p.get("is_solid"), "flat_volume_cm3": p.get("flat_volume_cm3")},
                     p.get("created") is True and p.get("is_solid") is True
                     and isinstance(p.get("flat_volume_cm3"), (int, float))
                     and 7.0 <= p["flat_volume_cm3"] <= 10.0)


def _flange_flat_present(p):
    row = _features_row(p, _PART)
    flat = (row or {}).get("flat_pattern") or {}
    return _measured("flange family flat pattern present", {"row": row},
                     row is not None and flat.get("present") is True and flat.get("healthy") is True)


def _bottom_match(p, area):
    """Select the downward-facing broad face - the OUTER bottom, not the shelled interior."""
    matches = [m for m in (p.get("matches") or [])
               if m.get("kind") == "planar_face" and (m.get("area") or 0) > area
               and (m.get("normal") or [0, 0, 0])[2] < -0.99]
    return matches[0] if len(matches) == 1 else None


def _bottom_face(area):
    def check(p):
        m = _bottom_match(p, area)
        return _measured("rip box outer bottom face", {"match": m}, m is not None and bool(m.get("handle")))
    return check


def _bottom_handle(area):
    return lambda p: _bottom_match(p, area)["handle"]


def _vertical_edges(p, length, z, count, tol=0.5):
    matches = [m for m in (p.get("matches") or [])
               if m.get("kind") == "line_edge" and _near(m.get("length"), length, tol)
               and _near((m.get("position") or [None, None, None])[2], z, tol)]
    return matches if len(matches) == count else None


def _four_verticals_check(p):
    rows = _vertical_edges(p, 40, 20, 4)
    return _measured("rip box four corner edges", {"count": len(p.get("matches") or [])},
                     rows is not None)


def _four_verticals_handles(p):
    return [m["handle"] for m in _vertical_edges(p, 40, 20, 4)]


def _outer_cylinders(p, radius=4, tol=0.3):
    return [m for m in (p.get("matches") or [])
            if m.get("kind") == "cylinder_face" and _near(m.get("radius"), radius, tol)
            and abs((m.get("axis") or [0, 0, 0])[2]) > 0.9]


def _corner_cylinder_census(p):
    cyls = _outer_cylinders(p)
    return _measured("rip box outer corner cylinders", {"count": len(cyls)}, len(cyls) == 4)


def _first_cylinder_save(p):
    c = _outer_cylinders(p)[0]
    return {"handle": c["handle"], "position": c["position"]}


def _rip_created(mode, new_bodies=()):
    """Require a landed rip of the given mode with a measured volume drop and the given split."""
    def check(p):
        return _measured("rip landed", {"mode": p.get("mode"),
                         "faces": (p.get("faces_before"), p.get("faces_after")),
                         "volume": (p.get("volume_before_cm3"), p.get("volume_after_cm3")),
                         "new_bodies": p.get("new_bodies")},
                         p.get("created") is True and p.get("mode") == mode
                         and isinstance(p.get("volume_before_cm3"), (int, float))
                         and isinstance(p.get("volume_after_cm3"), (int, float))
                         and p["volume_after_cm3"] < p["volume_before_cm3"]
                         and p.get("new_bodies") == list(new_bodies))
    return check


def _face_rip_landed(p):
    """Require a face rip to publish no gap and to remove the whole R4/r2.5 x 40 mm bend region."""
    return _rip_created("face")(p) and _measured(
        "face rip takes no gap", {"gap_mm": p.get("gap_mm"), "gap_source": p.get("gap_source"),
                                  "volume_removed_cm3": p.get("volume_removed_cm3")},
        "gap_mm" not in p and "gap_source" not in p
        and _near(p.get("volume_removed_cm3"), 0.306305, 0.001))


def _oblique_flange_created(p):
    """Require a base flange on the 30 deg plane to read its fresh component's 2.5 mm rule thickness."""
    return _measured("oblique base flange thickness", {"bodies": (p.get("bodies_before"), p.get("bodies_after")),
                     "thickness_mm": p.get("thickness_mm"), "rule": p.get("rule")},
                     p.get("created") is True and p.get("kind") == "base"
                     and isinstance(p.get("bodies_before"), int) and isinstance(p.get("bodies_after"), int)
                     and p["bodies_after"] == p["bodies_before"] + 1
                     and _near(p.get("thickness_mm"), 2.5, 0.001) and p.get("rule") == "Steel (mm)")


def _oblique_slab_faces(p):
    """Require find_geometry's own read of the slab's two 80 x 40 mm faces: tilted off Z, 2.5 mm apart."""
    broad = [m for m in (p.get("matches") or []) if m.get("kind") == "planar_face"
             and _near(m.get("area"), 3200.0, 1.0) and m.get("normal") and m.get("position")]
    gap = tilt = None
    if len(broad) == 2:
        n, a, b = broad[0]["normal"], broad[0]["position"], broad[1]["position"]
        gap, tilt = abs(sum((b[i] - a[i]) * n[i] for i in range(3))), abs(n[2])
    return _measured("oblique slab faces read independently",
                     {"broad_faces": len(broad), "gap_mm": gap, "normal_z": tilt},
                     gap is not None and _near(gap, 2.5, 0.01) and tilt < 0.99)


def _other_corner_edge(p, used_xy, min_sep=10):
    """A vertical tangent-line edge belonging to a DIFFERENT corner than used_xy."""
    if not used_xy:
        return None
    for m in p.get("matches") or []:
        if m.get("kind") != "line_edge" or not _near(m.get("length"), 40, 0.5):
            continue
        pos = m.get("position") or [None, None, None]
        if pos[0] is None:
            continue
        dist = ((pos[0] - used_xy[0]) ** 2 + (pos[1] - used_xy[1]) ** 2) ** 0.5
        if dist > min_sep:
            return m
    return None


def _other_corner_edge_check(p):
    used = _RECALL.get("sm_rip_cyl") or {}
    m = _other_corner_edge(p, used.get("position"))
    return _measured("rip box another corner's vertical edge",
                     {"match": m, "used_position": used.get("position"), "count": len(p.get("matches") or [])},
                     m is not None and bool(m.get("handle")))


def _other_corner_edge_save(p):
    used = _RECALL.get("sm_rip_cyl") or {}
    m = _other_corner_edge(p, used.get("position"))
    return {"handle": m["handle"], "position": m["position"]}


def _vertex_near(p, x, y, z, tol=0.5):
    matches = [m for m in (p.get("matches") or [])
               if m.get("kind") == "vertex"
               and _near((m.get("position") or [None, None, None])[0], x, tol)
               and _near((m.get("position") or [None, None, None])[1], y, tol)
               and _near((m.get("position") or [None, None, None])[2], z, tol)]
    return matches[0] if len(matches) == 1 else None


def _rip_vertex_pair(p):
    edge = _RECALL.get("sm_rip_edge") or {}
    pos = edge.get("position") or [None, None, None]
    v1 = _vertex_near(p, pos[0], pos[1], 0)
    v2 = _vertex_near(p, pos[0], pos[1], 40)
    return {"v1": v1["handle"] if v1 else None, "v2": v2["handle"] if v2 else None}


def _rip_vertex_pair_check(p):
    pair = _rip_vertex_pair(p)
    pair["count"] = len(p.get("matches") or [])
    return _measured("rip box one-edge vertex pair", pair, bool(pair.get("v1")) and bool(pair.get("v2")))


def _scratch_session(label):
    """Require a further scratch session, distinct from home and the flange coupon."""
    def check(p):
        return _measured(label, p,
                         p.get("created") is True and p.get("is_active") is True
                         and str(p.get("document_handle") or "").startswith("session:")
                         and p.get("document_handle") != _RECALL.get("sm_home")
                         and p.get("document_handle") != _RECALL.get("sm_coupon"))
    return check


_join_session = _scratch_session("isolated join session")
_rip_session = _scratch_session("isolated rip session")


def _plateB_match(p):
    """The plate's wide face that looks toward plate A (normal -X): the xz sketch's y axis maps to
    -Z and the extrude runs +Y, so the plate stands at x 120..121.5, y 0..40, z 10..40."""
    matches = [m for m in (p.get("matches") or [])
               if m.get("kind") == "planar_face" and (m.get("area") or 0) > 500
               and (m.get("normal") or [0, 0, 0])[0] < -0.99]
    return matches[0] if len(matches) == 1 else None


def _plateB_face_check(p):
    m = _plateB_match(p)
    return _measured("join plate B wide face", {"match": m}, m is not None and bool(m.get("handle")))


def _plateB_face_handle(p):
    return _plateB_match(p)["handle"]


def _plateB_edge_match(p):
    """Plate B's bottom rim edge on the face toward plate A: x=120, z=10, length 20."""
    return _edge_match(p, x=120, z=10, length=20)


def _plateB_edge_check(p):
    m = _plateB_edge_match(p)
    return _measured("join plate B bottom rim edge", {"match": m}, m is not None and bool(m.get("handle")))


def _plateB_edge_handle(p):
    return _plateB_edge_match(p)["handle"]


def _converted_second(p):
    """Require a second body converted under the component's active rule: plate A's convert
    renamed the design rule '<name> (Convert)', so the requested name no longer resolves."""
    return _measured("second body converted under the active rule", {"applied": p.get("applied_rule"),
                     "thickness_cm": p.get("applied_rule_thickness_cm"), "prior": p.get("prior_active_rule")},
                     p.get("converted") is True and p.get("requested_rule") == "active"
                     and p.get("applied_rule") == p.get("prior_active_rule")
                     and _near(p.get("measured_blank_thickness_cm"), 0.15, 1e-6)
                     and _near(p.get("applied_rule_thickness_cm"), 0.15, 1e-6))


def _join_created(bends_before, radius_mm):
    """Require the merge, the bend faces both plates carried plus two, and the landed radius."""
    def check(p):
        return _measured("join by bend merged bodies", {"bodies": (p.get("bodies_before"), p.get("bodies_after")),
                         "bend_faces": (p.get("bend_faces_before"), p.get("bend_faces_after")),
                         "bend_radius_mm": p.get("bend_radius_mm")},
                         p.get("created") is True and p.get("bodies_before") == 2 and p.get("bodies_after") == 1
                         and p.get("bend_faces_before") == bends_before
                         and p.get("bend_faces_after") == bends_before + 2
                         and p.get("uses_rule_radius") is False
                         and _near(p.get("bend_radius_mm"), radius_mm, 1e-6))
    return check


def _join_created_no_radius(bends_before):
    """Require the merge to land with no override requested and the rule's own radius applied."""
    def check(p):
        return _measured("join by bend merged with the rule's own radius",
                         {"bodies": (p.get("bodies_before"), p.get("bodies_after")),
                          "bend_faces": (p.get("bend_faces_before"), p.get("bend_faces_after")),
                          "uses_rule_radius": p.get("uses_rule_radius")},
                         p.get("created") is True
                         and isinstance(p.get("bodies_before"), int) and isinstance(p.get("bodies_after"), int)
                         and p["bodies_after"] == p["bodies_before"] - 1
                         and p.get("bend_faces_before") == bends_before
                         and p.get("bend_faces_after") == bends_before + 2
                         and p.get("uses_rule_radius") is True)
    return check


def _join_radius_read(radius_mm):
    """Require exactly one cylinder at the requested inner radius on the joined body."""
    def check(p):
        hits = [m for m in (p.get("matches") or []) if m.get("kind") == "cylinder_face"
                and _near(m.get("radius"), radius_mm, 0.01)]
        return _measured("join bend inner radius", {"hits": len(hits), "count": len(p.get("matches") or [])},
                         len(hits) == 1)
    return check


def _rip_volume_read(key):
    """Require the mass read (mm3) to agree with the rip's own volume_after_cm3."""
    def check(p):
        volume_mm3 = (p.get("mass") or {}).get("volume")
        reported = _RECALL.get(key)
        return _measured("rip volume independently read", {"mass_mm3": volume_mm3, "reported_cm3": reported},
                         isinstance(volume_mm3, (int, float)) and isinstance(reported, (int, float))
                         and _near(volume_mm3, reported * 1000.0, max(0.5, reported * 1000.0 * 0.001)))
    return check


def _one_body(p):
    per_body = p.get("mass") or {}
    return _measured("join body count", {"count": per_body.get("per_body_count")},
                     per_body.get("per_body_count") == 1)


def _capture_flange_height(p):
    feature = _RECALL.get("flange_height_feature")
    rows = [r for r in (p.get("timeline") or {}).get("timeline", [])
            if r.get("name") == feature and r.get("component") == _PART]
    params = (rows[0].get("params") or []) if len(rows) == 1 else []
    matches = [r for r in params if r.get("role") == "FlangeHeight"]
    name = matches[0].get("name") if len(matches) == 1 else None
    if name:
        _RECALL["flange_height_parameter"] = name
    return _measured("one scoped flange height parameter", {"feature": feature,
                     "rows": len(rows), "matches": matches},
                     len(rows) == 1 and len(matches) == 1 and bool(name)
                     and matches[0].get("expression") == "20 mm" and _healthy_timeline(p))


def _read_flange_height(expression, value):
    def check(p):
        rows = [r for r in (p.get("timeline") or {}).get("timeline", [])
                if r.get("name") == _RECALL.get("flange_height_feature")
                and r.get("component") == _PART]
        params = (rows[0].get("params") or []) if len(rows) == 1 else []
        matches = [r for r in params if r.get("name") == _RECALL.get("flange_height_parameter")]
        got = matches[0] if len(matches) == 1 else {}
        return _measured("flange height expression and value", got,
                         len(matches) == 1 and got.get("role") == "FlangeHeight"
                         and got.get("expression") == expression and _near(got.get("value"), value, 1e-6)
                         and _healthy_timeline(p))
    return check


def _flange_height_effect(expected_height, volume_delta):
    def check(p):
        mass = p.get("mass") or {}
        bbox = {axis: p.get(axis) for axis in "xyz"}
        return _measured("flange parameter drives landed body", {
            "bbox": bbox, "volume": mass.get("volume"),
            "parameter": _RECALL.get("flange_height_parameter")},
            _near(p.get("z"), expected_height, .05)
            and _near(mass.get("volume"),
                      _RECALL.get("flange_landed_volume", 0) + volume_delta, .02))
    return check


def _capture_flange_landed_volume(p):
    volume = (p.get("mass") or {}).get("volume")
    if isinstance(volume, (int, float)):
        _RECALL["flange_landed_volume"] = volume
    return _measured("landed flange volume baseline", {"volume": volume, "z": p.get("z")},
                     isinstance(volume, (int, float)) and _near(p.get("z"), 20, .05))


def _healthy_timeline(p):
    timeline = p.get("timeline") or {}
    summary = timeline.get("summary") or {}
    rows = timeline.get("timeline") or []
    return (timeline.get("truncated", False) is False and timeline.get("returned") == timeline.get("count")
            and set(summary.get("states") or {}) == {"healthy"}
            and isinstance(summary.get("exceptions"), list) and not summary.get("exceptions")
            and all(r.get("health", "healthy") == "healthy"
                    and r.get("is_rolled_back", False) is False for r in rows))


def _flange_baseline(p):
    rows = (p.get("timeline") or {}).get("timeline") or []
    state = [(r.get("name"), r.get("type"), r.get("health", "healthy")) for r in rows]
    _RECALL["flange_refusal_timeline"] = state
    return _measured("flange refusal timeline baseline", state,
                     bool(state) and _healthy_timeline(p))


def _flange_refusal_timeline(p):
    rows = (p.get("timeline") or {}).get("timeline") or []
    state = [(r.get("name"), r.get("type"), r.get("health", "healthy")) for r in rows]
    return _measured("numeric-only flange refusal preserves timeline", state,
                     state == _RECALL.get("flange_refusal_timeline")
                     and _healthy_timeline(p))


def _flange_blank_state(p, compare=False):
    mass = p.get("mass") or {}
    state = {"min": p.get("min_point"), "max": p.get("max_point"),
             "volume": mass.get("volume"), "body_count": mass.get("per_body_count")}
    if not compare:
        _RECALL["flange_refusal_body"] = state
    return _measured("numeric-only flange refusal preserves blank body", state,
                     bool(state["min"]) and bool(state["max"])
                     and _near(state["volume"], _RECALL.get("flange_refusal_body", {}).get("volume"), .01)
                     and state["min"] == _RECALL.get("flange_refusal_body", {}).get("min")
                     and state["max"] == _RECALL.get("flange_refusal_body", {}).get("max")
                     and state["body_count"] == _RECALL.get("flange_refusal_body", {}).get("body_count"))


_SHEET_FLANGE = _SHEET_BUILD[:-1] + [
    # --- native edge flanges off the SAME rule (R=2, T=1.5, K=0.42, all mm): the bend bulges the
    # rim by R+T=3.5 mm and an OUTER-datum distance reaches that height exactly --------------------
    ("model_inspect", {"target": _PART, "include": ["default"]}, _blank_extent, None),
    ("find_geometry", {"target": _PART, "kind": "line_edge", "max_results": 40},
     _one_edge("blank rim edge at x=80", x=80, z=1.5, length=40),
     ("sm_edge_x80", _edge_handle(x=80, z=1.5, length=40))),
    ("param_add", {"name": "FlangeWitnessH", "expression": "12 mm", "unit": "mm"},
     lambda p: p.get("added") is True and (p.get("parameter") or {}).get("name") == "FlangeWitnessH", None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _flange_baseline, None),
    ("model_inspect", {"target": _PART, "include": ["default", "mass"], "per_body": True, "units": "mm",
                        "accuracy": "very_high"}, lambda p: _flange_blank_state(p), None),
    ("sheet_create_flange", lambda c: {"kind": "edge",
                                        "edges": [_ctx_get(c, "sm_edge_x80", "blank rim edge at x=80")],
                                        "distance": "FlangeWitnessH"},
     _refused("'distance' must be a number"), None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _flange_refusal_timeline, None),
    ("model_inspect", {"target": _PART, "include": ["default", "mass"], "per_body": True, "units": "mm",
                        "accuracy": "very_high"}, lambda p: _flange_blank_state(p, True), None),
    ("sheet_create_flange", lambda c: {"kind": "edge",
                                        "edges": [_ctx_get(c, "sm_edge_x80", "blank rim edge at x=80")],
                                        "distance": 20}, _flange_created(),
     ("flange_height_feature", _recall("flange_height_feature", lambda p: p["feature"]))),
    ("model_inspect", {"target": _PART, "include": ["default", "mass"], "per_body": True,
                        "units": "mm", "accuracy": "very_high"}, _capture_flange_landed_volume, None),
    ("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
     _capture_flange_height, None),
    ("param_set", lambda c: {"name": _RECALL.get("flange_height_parameter"),
                              "expression": "FlangeWitnessH"}, "ok", None),
    ("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
     _read_flange_height("FlangeWitnessH", 1.2), None),
    ("model_inspect", {"target": _PART, "include": ["default", "mass"], "units": "mm",
                        "accuracy": "very_high"}, _flange_height_effect(12, -480), None),
    ("param_set", {"name": "FlangeWitnessH", "expression": "20 mm"}, "ok", None),
    ("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
     _read_flange_height("FlangeWitnessH", 2.0), None),
    ("model_inspect", {"target": _PART, "include": ["default", "mass"], "units": "mm",
                        "accuracy": "very_high"}, _flange_height_effect(20, 0), None),
    ("model_inspect", {"target": _PART, "include": ["default"]}, _flange1_envelope, None),
    ("find_geometry", {"target": _PART, "kind": "line_edge", "max_results": 40},
     _one_edge("blank rim edge at x=0", x=0, z=1.5, length=40),
     ("sm_edge_x0", _edge_handle(x=0, z=1.5, length=40))),
    ("sheet_create_flange", lambda c: {"kind": "edge",
                                        "edges": [_ctx_get(c, "sm_edge_x0", "blank rim edge at x=0")],
                                        "distance": 15}, _flange_created(), None),
    ("model_inspect", {"target": _PART, "include": ["default"]}, _flange2_envelope, None),
    # --- refusal: a curved (bend) face -------------------------------------------------------------
    ("find_geometry", {"target": _PART, "kind": "line_edge", "max_results": 40},
     _one_edge("blank rim edge at y=40", x=40, y=40, z=1.5, length=80),
     ("sm_edge_y40", _edge_handle(x=40, y=40, z=1.5, length=80))),
    ("find_geometry", {"target": _PART, "kind": "line_edge", "max_results": 60},
     _bend_boundary_check, ("sm_edge_curved", _bend_boundary_handle)),
    ("sheet_create_flange", lambda c: {"kind": "edge",
                                        "edges": [_ctx_get(c, "sm_edge_curved", "flange bend-to-plane boundary line")],
                                        "distance": 10}, _refused("curved face"), None),
    # --- hem: a landed flat kind, then a rope hem refused for its missing dimensions --------------
    ("sheet_create_hem", lambda c: {"edge": _ctx_get(c, "sm_edge_y40", "blank rim edge at y=40"),
                                     "kind": "flat", "length": 8}, _hem_created("flat"), None),
    ("find_geometry", {"target": _PART, "kind": "line_edge", "max_results": 60},
     _one_edge("blank rim edge at y=0", x=40, y=0, z=1.5, length=80),
     ("sm_edge_y0", _edge_handle(x=40, y=0, z=1.5, length=80))),
    ("sheet_create_hem", lambda c: {"edge": _ctx_get(c, "sm_edge_y0", "blank rim edge at y=0"),
                                     "kind": "rope", "length": 8}, _refused("needs"), None),
    # --- an inner-height flange: inner 3 mm is outer 4.5 mm -----------------------------------------
    ("sheet_create_flange", lambda c: {"kind": "edge",
                                        "edges": [_ctx_get(c, "sm_edge_y0", "blank rim edge at y=0")],
                                        "distance": 3, "height_datum": "inner"}, _flange_created(), None),
    ("model_inspect", {"target": _PART, "include": ["default"]}, _inner_flange_envelope, None),
    # --- kind='base': a closed profile in the active sheet component adopts its rule, and a
    # profile owned by a DIFFERENT component is refused before any mutation -------------------------
    ("sheet_create_flange", lambda c: {"kind": "base",
                                        "profile": {"sketch": _SEED_BASE, "profile_index": 0}},
     _refused("not the active component"), None),
    ("sketch_create", {"name": _BASE_KIND_PROFILE, "plane": "xy"}, "ok", None),
    ("sketch_add_geometry", {"sketch_name": _BASE_KIND_PROFILE, "geometry": [
        {"kind": "rectangle", "x1": 200, "y1": 0, "x2": 240, "y2": 20}]}, "ok", None),
    ("sheet_create_flange", lambda c: {"kind": "base",
                                        "profile": {"sketch": _BASE_KIND_PROFILE, "profile_index": 0}},
     _base_flange_created, None),
    # --- a two-edge call on that fresh body's own rim: both edges land in one call (+4 bend faces),
    # each bulging its own side by R+T=3.5 mm at the requested 10 mm OUTER height -------------------
    # the part now holds close to a hundred line edges, so each finder asks nearest-first
    ("find_geometry", {"target": _PART, "kind": "line_edge", "nearest_to": [220, 0, 1.5], "max_results": 8},
     _one_edge("base-flange body edge at y=0", x=220, y=0, z=1.5, length=40),
     ("sm_base_edge_y0", _edge_handle(x=220, y=0, z=1.5, length=40))),
    ("find_geometry", {"target": _PART, "kind": "line_edge", "nearest_to": [220, 20, 1.5], "max_results": 8},
     _one_edge("base-flange body edge at y=20", x=220, y=20, z=1.5, length=40),
     ("sm_base_edge_y20", _edge_handle(x=220, y=20, z=1.5, length=40))),
    ("sheet_create_flange", lambda c: {"kind": "edge",
                                        "edges": [_ctx_get(c, "sm_base_edge_y0", "base-flange body edge at y=0"),
                                                  _ctx_get(c, "sm_base_edge_y20", "base-flange body edge at y=20")],
                                        "distance": 10}, _flange_created(edge_count=2),
     ("sm_base_body", _recall("sm_base_body", lambda p: p["body"]))),
    ("find_geometry", {"target": _PART, "kind": "vertex", "max_results": 200},
     _two_edge_tips_check, None),
    # --- unfold/refold: the base-flange body's own two bends, verified flat then restored; a
    # pending unfold blocks every later unfold in the design, so it is refolded right here --------
    ("find_geometry", lambda c: {"target": _ctx_get(c, "sm_base_body", "base-flange body"),
                                 "kind": "planar_face", "nearest_to": [220, 10, 1.5],
                                 "max_results": 8},
     _top_face(700), _top_handle(700)),
    ("sheet_create_unfold", lambda c: {"stationary_face": _ctx_get(c, "sm_top", "base-flange body top face"),
                                        "all_bends": True}, _base_body_unfolded(2),
     ("sm_base_unfold", _recall("sm_base_unfold", lambda p: p["feature"]))),
    ("model_inspect", lambda c: {"target": _ctx_get(c, "sm_base_body", "base-flange body")},
     _base_body_flat, None),
    ("sheet_create_refold", lambda c: {"unfold": _ctx_get(c, "sm_base_unfold", "base-flange body unfold feature")},
     _base_body_refolded, None),
    ("model_inspect", lambda c: {"target": _ctx_get(c, "sm_base_body", "base-flange body")},
     _base_body_refolded_extent, None),
    # --- flip: on the same body's x=240 edge, a 10 mm flipped flange reaches -(10 - T) = -8.5 mm ---
    ("find_geometry", {"target": _PART, "kind": "line_edge", "nearest_to": [240, 10, 1.5], "max_results": 8},
     _one_edge("base-flange body edge at x=240", x=240, y=10, z=1.5, length=20),
     ("sm_base_edge_x240", _edge_handle(x=240, y=10, z=1.5, length=20))),
    ("sheet_create_flange", lambda c: {"kind": "edge",
                                        "edges": [_ctx_get(c, "sm_base_edge_x240", "base-flange body edge at x=240")],
                                        "distance": 10, "flip": True}, _flange_created(), None),
    ("model_inspect", {"target": _PART, "include": ["default"]}, _flip_flange_envelope, None),
    # --- census: the flange family's own feature slice ---------------------------------------------
    ("sheet_get", {"include": ["features"]}, _flange_family_census, None),
    # --- flat pattern over the whole flanged+hemmed part --------------------------------------------
    ("find_geometry", {"target": _PART, "kind": "planar_face", "max_results": 60},
     _top_face(3000), _top_handle(3000)),
    ("sheet_create_flat_pattern", lambda c: {"stationary_face": _ctx_get(c, "sm_top", "flange family stationary face")},
     _flange_flat_created, None),
    ("sheet_get", {"include": ["features"]}, _flange_flat_present, None),
    # --- rip rig: a filleted-corner shelled box in its own scratch document (the blank's convert
    # renamed the coupon's rule copy, so a second convert there cannot name the rule) --------------
    ("doc_new", {}, _rip_session, ("sm_rip", _recall("sm_rip", lambda p: p["document_handle"]))),
    ("model_create_component", {"name": _RIP_SEED, "sheet_metal": True, "activate": True}, "ok", None),
    ("sheet_edit_rule", {"rule": "library:Steel (mm)", "name": _RULE, "thickness": "1.5 mm",
                         "bend_radius": "2 mm", "gap": "0.5 mm", "k_factor": 0.4}, "ok", None),
    ("sheet_edit_rule", {"action": "update", "rule": "design:" + _RULE, "k_factor": 0.42}, "ok", None),
    ("model_create_component", {"name": _RIP_BOX, "activate": True}, "ok", None),
    ("sketch_create", {"name": _RIP_BASE, "plane": "xy"}, "ok", None),
    ("sketch_add_geometry", {"sketch_name": _RIP_BASE, "geometry": [
        {"kind": "rectangle", "x1": 200, "y1": 0, "x2": 260, "y2": 60}]}, "ok", None),
    ("model_extrude", {"sketch_name": _RIP_BASE, "profile_index": 0,
                       "distance": 40, "operation": "new"}, _extruded, None),
    ("find_geometry", {"target": _RIP_BOX, "kind": "line_edge", "max_results": 40},
     _four_verticals_check, ("sm_rip_verticals", _four_verticals_handles)),
    ("model_fillet", lambda c: {"edges": _ctx_get(c, "sm_rip_verticals", "rip box corner edges"),
                                "radius": 4}, "ok", None),
    ("find_geometry", {"target": _RIP_BOX, "kind": "planar_face", "max_results": 30},
     _top_face(3000), _top_handle(3000)),
    ("model_shell", lambda c: {"remove_faces": [_ctx_get(c, "sm_top", "rip box top face")],
                               "thickness": 1.5, "direction": "inside"}, "ok", None),
    ("find_geometry", {"target": _RIP_BOX, "kind": "planar_face", "max_results": 30},
     _bottom_face(3000), ("sm_rip_bottom", _bottom_handle(3000))),
    ("sheet_convert", lambda c: {"body": _RIP_BOX, "base_face": _ctx_get(c, "sm_rip_bottom", "rip box outer bottom face"),
                                  "rule": "design:" + _RULE}, _converted, None),
    ("find_geometry", {"target": _RIP_BOX, "kind": "cylinder_face", "max_results": 30},
     _corner_cylinder_census, ("sm_rip_cyl", _recall("sm_rip_cyl", _first_cylinder_save))),
    # a face rip takes no gap: an explicit one is refused before anything is ripped
    ("sheet_create_rip", lambda c: {"mode": "face",
                                    "face": _ctx_get(c, "sm_rip_cyl", "rip box outer corner cylinder")["handle"],
                                    "gap": 1}, _refused("does not apply to mode='face'", "takes no gap"), None),
    ("sheet_create_rip", lambda c: {"mode": "face",
                                    "face": _ctx_get(c, "sm_rip_cyl", "rip box outer corner cylinder")["handle"]},
     _face_rip_landed, ("sm_rip_vol_face", _recall("sm_rip_vol_face", lambda p: p["volume_after_cm3"]))),
    ("model_inspect", {"target": _RIP_BOX, "include": ["mass"]}, _rip_volume_read("sm_rip_vol_face"), None),
    ("find_geometry", {"target": _RIP_BOX, "kind": "line_edge", "max_results": 40},
     _other_corner_edge_check, ("sm_rip_edge", _recall("sm_rip_edge", _other_corner_edge_save))),
    ("sheet_create_rip", lambda c: {"mode": "along_edge",
                                    "edge": _ctx_get(c, "sm_rip_edge", "rip box another corner's edge")["handle"],
                                    "gap": 1}, _rip_created("along_edge", new_bodies=[]),
     ("sm_rip_vol_edge", _recall("sm_rip_vol_edge", lambda p: p["volume_after_cm3"]))),
    ("model_inspect", {"target": _RIP_BOX, "include": ["mass"]}, _rip_volume_read("sm_rip_vol_edge"), None),
    ("find_geometry", {"target": _RIP_BOX, "kind": "vertex", "max_results": 60},
     _rip_vertex_pair_check, ("sm_rip_vertices", _recall("sm_rip_vertices", _rip_vertex_pair))),
    ("sheet_create_rip", lambda c: {"mode": "between_points",
                                    "point_one": _ctx_get(c, "sm_rip_vertices", "rip box one-edge vertex pair")["v1"],
                                    "point_two": _ctx_get(c, "sm_rip_vertices", "rip box one-edge vertex pair")["v2"],
                                    "gap": 1}, _refused("same edge"), None),
    # --- a base flange on a plane 30 deg off XY, hinged on a helper block's edge: its thickness is
    # read off the slab's own faces, then read again independently by find_geometry -----------------
    ("model_create_component", {"name": _OBLIQUE, "sheet_metal": True, "activate": True}, "ok", None),
    ("sketch_create", {"name": _OBLIQUE_HINGE, "plane": "xy"}, "ok", None),
    ("sketch_add_geometry", {"sketch_name": _OBLIQUE_HINGE, "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": -10, "x2": 80, "y2": 0}]}, "ok", None),
    ("model_extrude", {"sketch_name": _OBLIQUE_HINGE, "profile_index": 0,
                       "distance": 5, "operation": "new"}, _extruded, None),
    ("find_geometry", {"target": _OBLIQUE, "kind": "line_edge", "max_results": 20},
     _one_edge("oblique hinge edge at y=0, z=0", x=40, y=0, z=0, length=80),
     ("sm_oblique_hinge", _edge_handle(x=40, y=0, z=0, length=80))),
    ("model_construction", lambda c: {"kind": "plane", "mode": "at_angle", "plane": "xy",
                                      "edges": [_ctx_get(c, "sm_oblique_hinge", "oblique hinge edge")],
                                      "angle": 30, "name": _OBLIQUE_PLANE}, "ok", None),
    ("sketch_create", {"name": _OBLIQUE_PROFILE, "plane": _OBLIQUE_PLANE}, "ok", None),
    ("sketch_add_geometry", {"sketch_name": _OBLIQUE_PROFILE, "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 80, "y2": 40}]}, "ok", None),
    ("sheet_create_flange", {"kind": "base", "profile": {"sketch": _OBLIQUE_PROFILE, "profile_index": 0}},
     _oblique_flange_created, None),
    ("find_geometry", {"target": _OBLIQUE, "kind": "planar_face", "max_results": 30},
     _oblique_slab_faces, None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "sm_rip", "rip scratch session"), "save_changes": False},
     _closed_one, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "sm_coupon", "flange coupon session")}, "ok", None),
    # --- join-by-bend rig: a fresh scratch document, two plates, one merged body --------------------
    ("doc_new", {}, _join_session, ("sm_join", _recall("sm_join", lambda p: p["document_handle"]))),
    ("model_create_component", {"name": _JOIN_SEED, "sheet_metal": True, "activate": True}, "ok", None),
    ("sheet_edit_rule", {"rule": "library:Steel (mm)", "name": _RULE, "thickness": "1.5 mm",
                         "bend_radius": "2 mm", "gap": "0.5 mm", "k_factor": 0.4}, "ok", None),
    ("sheet_edit_rule", {"action": "update", "rule": "design:" + _RULE, "k_factor": 0.42}, "ok", None),
    ("model_create_component", {"name": _JOIN, "activate": True}, "ok", None),
    ("sketch_create", {"name": _JOIN_A, "plane": "xy"}, "ok", None),
    ("sketch_add_geometry", {"sketch_name": _JOIN_A, "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 100, "y2": 40}]}, "ok", None),
    ("model_extrude", {"sketch_name": _JOIN_A, "profile_index": 0,
                       "distance": 1.5, "operation": "new"}, _extruded, None),
    # plate A becomes an L (a 40 x 20 notch), so its notch edge is REENTRANT for the flange below
    ("sketch_create", {"name": _JOIN_A_NOTCH, "plane": "xy"}, "ok", None),
    ("sketch_add_geometry", {"sketch_name": _JOIN_A_NOTCH, "geometry": [
        {"kind": "rectangle", "x1": 60, "y1": 20, "x2": 100, "y2": 40}]}, "ok", None),
    ("model_extrude", {"sketch_name": _JOIN_A_NOTCH, "profile_index": 0,
                       "distance": 1.5, "operation": "cut"}, _extruded, None),
    ("sketch_create", {"name": _JOIN_B, "plane": "xz"}, "ok", None),
    ("sketch_add_geometry", {"sketch_name": _JOIN_B, "geometry": [
        {"kind": "rectangle", "x1": 120, "y1": -10, "x2": 121.5, "y2": -40}]}, "ok", None),
    ("model_extrude", {"sketch_name": _JOIN_B, "profile_index": 0,
                       "distance": 20, "operation": "new"}, _extruded, None),
    ("find_geometry", {"target": "Body1", "kind": "planar_face", "max_results": 20},
     _top_face(3000), ("sm_join_top_a", lambda p: _top_match(p, 3000)["handle"])),
    ("sheet_convert", lambda c: {"body": "Body1", "base_face": _ctx_get(c, "sm_join_top_a", "plate A top face"),
                                  "rule": "design:" + _RULE}, _converted, None),
    ("find_geometry", {"target": "Body2", "kind": "planar_face", "max_results": 20},
     _plateB_face_check, ("sm_join_top_b", _plateB_face_handle)),
    ("sheet_convert", lambda c: {"body": "Body2", "base_face": _ctx_get(c, "sm_join_top_b", "plate B wide face"),
                                  "rule": "active"}, _converted_second, None),
    # The L's reentrant notch edge takes a plain edge flange like any other rim edge.
    ("find_geometry", {"target": "Body1", "kind": "line_edge", "max_results": 40},
     _one_edge("plate A reentrant notch edge at y=20", x=80, y=20, z=1.5, length=40),
     ("sm_join_notch", _edge_handle(x=80, y=20, z=1.5, length=40))),
    ("sheet_create_flange", lambda c: {"kind": "edge",
                                        "edges": [_ctx_get(c, "sm_join_notch", "plate A reentrant notch edge")],
                                        "distance": 10}, _flange_created(), None),
    # Plate B carries a flange BEFORE the join, so the join must count both plates' bends: plate
    # A's notch-edge flange above and plate B's own top-rim flange each add 2 (see _join_created).
    ("find_geometry", {"target": "Body2", "kind": "line_edge", "max_results": 40},
     _one_edge("plate B top rim edge at z=40", x=120, z=40, length=20),
     ("sm_join_b_top", _edge_handle(x=120, z=40, length=20))),
    ("sheet_create_flange", lambda c: {"kind": "edge",
                                        "edges": [_ctx_get(c, "sm_join_b_top", "plate B top rim edge")],
                                        "distance": 10}, _flange_created(), None),
    ("find_geometry", {"target": "Body1", "kind": "line_edge", "max_results": 40},
     _one_edge("plate A top rim edge at x=100", x=100, z=1.5, length=20),
     ("sm_join_edge_a", _edge_handle(x=100, z=1.5, length=20))),
    ("find_geometry", {"target": "Body2", "kind": "line_edge", "max_results": 30},
     _plateB_edge_check, ("sm_join_edge_b", _plateB_edge_handle)),
    # bends_before=4: plate A's notch-edge flange (+2) plus plate B's top-rim flange (+2).
    ("sheet_create_join_by_bend", lambda c: {"edge_one": _ctx_get(c, "sm_join_edge_a", "plate A top rim edge"),
                                             "edge_two": _ctx_get(c, "sm_join_edge_b", "plate B bottom rim edge"),
                                             "bend_radius": 5},
     _join_created(4, 5), None),
    ("find_geometry", {"target": "Body1", "kind": "cylinder_face", "radius": 5, "max_results": 20},
     _join_radius_read(5), None),
    ("model_inspect", {"target": _JOIN + ":1", "include": ["mass"], "per_body": True}, _one_body, None),
    # --- a second pair, joined with NO bend_radius: the merge takes the rule's own 2 mm radius ------
    ("sketch_create", {"name": _JOIN_E_BASE, "plane": "xy"}, "ok", None),
    ("sketch_add_geometry", {"sketch_name": _JOIN_E_BASE, "geometry": [
        {"kind": "rectangle", "x1": 180, "y1": 0, "x2": 200, "y2": 20}]}, "ok", None),
    ("model_extrude", {"sketch_name": _JOIN_E_BASE, "profile_index": 0,
                       "distance": 1.5, "operation": "new"}, _extruded,
     ("sm_join_e_body", _recall("sm_join_e_body", lambda p: p["result_bodies"][0]))),
    ("find_geometry", lambda c: {"target": _ctx_get(c, "sm_join_e_body", "plate E body"),
                                 "kind": "planar_face", "max_results": 20},
     _top_face(300), ("sm_join_top_e", lambda p: _top_match(p, 300)["handle"])),
    ("sheet_convert", lambda c: {"body": _ctx_get(c, "sm_join_e_body", "plate E body"),
                                 "base_face": _ctx_get(c, "sm_join_top_e", "plate E top face"),
                                 "rule": "active"}, _converted_second, None),
    ("sketch_create", {"name": _JOIN_F_BASE, "plane": "xz"}, "ok", None),
    ("sketch_add_geometry", {"sketch_name": _JOIN_F_BASE, "geometry": [
        {"kind": "rectangle", "x1": 200, "y1": -10, "x2": 201.5, "y2": -40}]}, "ok", None),
    ("model_extrude", {"sketch_name": _JOIN_F_BASE, "profile_index": 0,
                       "distance": 20, "operation": "new"}, _extruded,
     ("sm_join_f_body", _recall("sm_join_f_body", lambda p: p["result_bodies"][0]))),
    ("find_geometry", lambda c: {"target": _ctx_get(c, "sm_join_f_body", "plate F body"),
                                 "kind": "planar_face", "max_results": 20},
     _plateB_face_check, ("sm_join_top_f", _plateB_face_handle)),
    ("sheet_convert", lambda c: {"body": _ctx_get(c, "sm_join_f_body", "plate F body"),
                                 "base_face": _ctx_get(c, "sm_join_top_f", "plate F wide face"),
                                 "rule": "active"}, _converted_second, None),
    ("find_geometry", lambda c: {"target": _ctx_get(c, "sm_join_e_body", "plate E body"),
                                 "kind": "line_edge", "max_results": 20},
     _one_edge("plate E right rim edge at x=200", x=200, z=1.5, length=20),
     ("sm_join_edge_e", _edge_handle(x=200, z=1.5, length=20))),
    ("find_geometry", lambda c: {"target": _ctx_get(c, "sm_join_f_body", "plate F body"),
                                 "kind": "line_edge", "max_results": 20},
     _one_edge("plate F bottom rim edge at x=200", x=200, z=10, length=20),
     ("sm_join_edge_f", _edge_handle(x=200, z=10, length=20))),
    ("sheet_create_join_by_bend", lambda c: {"edge_one": _ctx_get(c, "sm_join_edge_e", "plate E right rim edge"),
                                             "edge_two": _ctx_get(c, "sm_join_edge_f", "plate F bottom rim edge")},
     _join_created_no_radius(0), None),
    ("find_geometry", lambda c: {"target": _ctx_get(c, "sm_join_e_body", "plate E body"),
                                 "kind": "cylinder_face", "radius": 2, "max_results": 20},
     _join_radius_read(2), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "sm_join", "join world session"), "save_changes": False},
     _closed_one, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "sm_coupon", "flange coupon session")}, "ok", None),
    # --- close the flange coupon and restore the original story session -----------------------------
    ("doc_close", lambda c: {"name": _ctx_get(c, "sm_coupon", "flange coupon session"), "save_changes": False},
     _closed_one, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "sm_home", "original story session")}, "ok", None),
    _dwell(4.0),
    ("doc_get", {"max_results": 1000}, _story_restored, None),
]


def _sheet_definition_before(key, field, kind):
    """Bank a complete rolled sheet definition with a usable public edit offer."""
    def check(p):
        definition = p.get("definition") or {}
        offers = definition.get("supported_edits") or []
        good = (definition.get("type") == kind and definition.get("unavailable") == {}
                and definition.get(field) is not None and bool(definition.get("feature_address"))
                and any(isinstance(row.get("call"), str) and "model_edit_feature(" in row["call"]
                        for row in offers))
        if good:
            _RECALL[key] = definition
        return _measured("rolled sheet definition and edit offer", definition, good)
    return check


def _sheet_edit_landed(p):
    """Require the setter's verified definition, identity, health and end marker."""
    return _measured("sheet definition edit", p,
        p.get("edited") is True and p.get("definition_matches") is True
        and p.get("same_feature") is True and p.get("owner_matches") is True
        and p.get("marker_restored") is True and p.get("new_timeline_errors") == []
        and p.get("new_timeline_warnings") == [])


def _sheet_edit_rows(feature_key, target, field, kind, payload, candidate=None, original=None):
    """Edit, independently read the landed field and geometry, restore and independently compare."""
    key = feature_key + "_" + (payload or {}).get("type", field)
    definition_key, shape_key = key + "_definition", key + "_shape"
    control = _RIP_SEED if kind == "RipFeature" else "SM Sweep Seed"
    def roll(ctx):
        return {"action": "roll", "feature": _ctx_get(ctx, feature_key, "sheet feature"), "to": "before"}
    end = {"action": "roll", "to": "end"}
    read = lambda ctx: {"include": ["definition"], "feature": _ctx_get(ctx, feature_key, "sheet feature")}
    inspect = {"target": target, "include": ["default", "mass"], "units": "mm",
               "per_body": True, "accuracy": "very_high"}
    action = "mode" if payload else "inputs"
    def edit(ctx, restore=False):
        baseline = _RECALL[definition_key]
        args = {"feature": baseline["feature_address"], "action": action}
        if payload:
            hem = baseline["hem"]
            args["hem"] = ({"type": hem["type"], "flip": hem["flip"],
                "bend_position": hem["bend_position"],
                **{name: dimension["expression"] for name, dimension in hem["dimensions"].items()}}
                if restore else dict(payload))
        else:
            args["references"] = [_ctx_get(ctx, key + "_restore", "fresh original Rip operand") if restore
                                   else _ctx_get(ctx, key + "_candidate", "fresh Rip operand")]
        return args
    def changed(p):
        before, after = _RECALL[definition_key], p.get("definition") or {}
        stable = all(_clean(after.get(name)) == _clean(value) for name, value in before.items()
                     if name not in (field, "supported_edits", "unavailable", "not_read", "note"))
        value = after.get(field) or {}
        if payload:
            dimensions = value.get("dimensions") or {}
            requested = {name: (number / 10 if name != "angle_deg" else number * 3.141592653589793 / 180)
                         for name, number in {"length": 9, "gap": 3, "radius": 4,
                                              "angle_deg": 180, "setback": 4}.items()
                         if name in payload}
            if payload["type"] == "double":
                requested["length"] = 1.2
            effect = (value.get("type") == payload["type"]
                and value.get("flip") == payload.get("flip", before[field]["flip"])
                and value.get("bend_position") == payload.get("bend_position", before[field]["bend_position"])
                and all(_near((dimensions.get(name) or {}).get(
                    "value_rad" if name == "angle_deg" else "value_cm"), number, 1e-8)
                    for name, number in requested.items()))
        else:
            effect = (_clean(value) != _clean(before[field])
                      and isinstance(value.get("geometry"), dict) and bool(value["geometry"]))
        good = stable and effect and after.get("unavailable") == {}
        if good:
            _RECALL[key + "_after"] = after
        return _measured("independent sheet definition read", after, good)
    rows = [("design_edit_timeline", roll, _roll_landed("before"), None),
            ("design_get", read, _sheet_definition_before(definition_key, field, kind), None)]
    if candidate:
        def save(p):
            matches = p.get("matches") or []
            if len(matches) != 1 or not matches[0].get("handle"):
                raise ValueError("fresh Rip operand needs one acquired geometry handle")
            _RECALL[key + "_candidate_desc"] = matches[0]
            return matches[0]["handle"]
        rows.append(("find_geometry", candidate, lambda p: len(p.get("matches") or []) == 1,
                     (key + "_candidate", _recall(key + "_candidate", save))))
    rows += [("design_edit_timeline", end, _roll_landed("end"), None),
             ("model_inspect", inspect, _shape_capture(shape_key, key + " baseline"), None)]
    if kind == "HemFeature":
        rows.append(("model_inspect", {**inspect, "target": control},
                     _shape_capture(key + "_control", key + " sibling baseline"), None))
    rows += [("model_edit_feature", edit, _sheet_edit_landed, None),
             ("design_edit_timeline", roll, _roll_landed("before"), None),
             ("design_get", read, changed,
              (key + "_landed_operand", lambda p: {"input_faces": [p["definition"][field]]})
              if candidate else None)]
    if candidate:
        rows.append(("sys_execute_script", lambda ctx: _draft_face_identity_args(
            ctx, key + "_candidate", key + "_landed_operand"), _draft_face_identity_check, None))
    rows += [
             ("sheet_get", {"include": ["features"]},
              lambda p: isinstance(p.get("features"), dict)
              and _sheet_disclosure(p, target, field, _RECALL[key + "_after"]), None),
             ("design_edit_timeline", end, _roll_landed("end"), None),
             ("model_inspect", inspect, _shape_changed(shape_key, key + " changed"), None)]
    if candidate:
        def original_read(p):
            matches = p.get("matches") or []
            baseline = _RECALL[definition_key][field].get("geometry")
            good = len(matches) == 1 and bool(matches[0].get("handle")) and bool(baseline)
            return _measured("reacquired original Rip operand before restoration", matches, good)
        rows += [("design_edit_timeline", roll, _roll_landed("before"), None),
                 ("find_geometry", original, original_read,
                  (key + "_restore", _recall(key + "_restore", lambda p: p["matches"][0]["handle"]))),
                 ("design_edit_timeline", end, _roll_landed("end"), None)]
    rows += [("model_edit_feature", lambda ctx: edit(ctx, True), _sheet_edit_landed, None),
             ("design_edit_timeline", roll, _roll_landed("before"), None),
             ("design_get", read, _definition_restored(definition_key, field), None),
             ("design_edit_timeline", end, _roll_landed("end"), None),
             ("model_inspect", inspect, _shape_restored(shape_key, key + " restored"), None)]
    if kind == "HemFeature":
        rows.append(("model_inspect", {**inspect, "target": control},
                     _shape_restored(key + "_control", key + " untouched sibling"), None))
    return rows


def _sheet_disclosure(p, component, field, expected):
    """Require sheet_get's bounded feature definition to agree with the separate design read."""
    rows = [row for row in (p.get("features") or {}).get("components") or []
            if row.get("component") == component]
    entries = (rows[0].get("hems" if field == "hem" else "rip_definitions") or []) if len(rows) == 1 else []
    return _measured("bounded sheet definition disclosure", entries,
        len(entries) == 1 and (entries[0].get("definition") or {}).get("unavailable") == {}
        and (entries[0].get("definition") or {}).get(field) is not None
        and _clean(entries[0]["definition"][field]) == _clean(expected[field]))


def _hem_edit_story():
    """Use one isolated flat blank for four supported Hem modes and each exact restoration."""
    rows = []
    for row in _SHEET_BUILD:
        rows.append(row)
        if row[0] == "sheet_convert" and row[2] is _converted:
            break
    rows += [("find_geometry", {"target": _PART, "kind": "line_edge", "max_results": 30},
              _one_edge("Hem editor flat rim", x=40, y=40, z=1.5, length=80),
              ("sm_hem_edit_edge", _edge_handle(x=40, y=40, z=1.5, length=80))),
             ("sheet_create_hem", lambda ctx: {"edge": _ctx_get(ctx, "sm_hem_edit_edge", "flat rim"),
                 "kind": "flat", "length": 8, "flip": True}, _hem_created("flat"),
              ("sm_hem_edit_feature", _recall("sm_hem_edit_feature", lambda p: _PART + "/" + p["feature"])))]
    for hem in ({"type": "flat", "length": "9 mm"},
                {"type": "open", "length": "9 mm", "gap": "3 mm", "bend_position": "tangent_to_side"},
                {"type": "rolled", "radius": "4 mm", "angle_deg": 180},
                {"type": "double", "length": "12 mm", "gap": "3 mm", "setback": "4 mm"}):
        rows += _sheet_edit_rows("sm_hem_edit_feature", _PART, "hem", "HemFeature", hem)
    rows += [("doc_close", lambda ctx: {"name": _ctx_get(ctx, "sm_coupon", "Hem coupon"),
                "save_changes": False}, _closed_one, None),
             ("doc_activate", lambda ctx: {"name": _ctx_get(ctx, "sm_home", "home")}, "ok", None),
             ("doc_get", {"max_results": 1000}, _story_restored, None)]
    return rows


_SHEET_FLANGE += _hem_edit_story()


def _rip_edit_story(kind):
    """Use a fresh rounded converted box for one same-kind Rip edit and restoration."""
    rows = [_SHEET_BUILD[0]]
    building = False
    for row in _SHEET_FLANGE:
        if row[0] == "doc_new" and row[2] is _rip_session:
            building = True
        if not building:
            continue
        rows.append(row)
        if row[0] == "sheet_convert" and row[2] is _converted:
            break
    key = "sm_rip_edit_" + kind
    query = {"target": _RIP_BOX, "kind": "cylinder_face" if kind == "face" else "line_edge",
             "nearest_to": [204, 4, 20] if kind == "face" else [260, 4, 20],
             "max_results": 1, "units": "mm"}
    if kind == "face":
        query["radius"] = 4
    def operand(p):
        matches = p.get("matches") or []
        good = (len(matches) == 1 and matches[0].get("kind") == query["kind"]
                and bool(matches[0].get("handle")))
        if kind == "face":
            good = good and _near(matches[0].get("radius"), 4, 1e-5)
        else:
            good = good and _near(matches[0].get("length"), 40, 1e-5)
        return _measured("fresh Rip creation operand", matches, good)
    rows.append(("find_geometry", query, operand,
                 (key + "_original", _recall(key + "_original", lambda p: p["matches"][0]["handle"]))))
    def create(ctx):
        args = {"mode": "face" if kind == "face" else "along_edge",
                "face" if kind == "face" else "edge": _ctx_get(ctx, key + "_original", "Rip operand")}
        if kind == "edge":
            args["gap"] = 1
        return args
    rows.append(("sheet_create_rip", create, _rip_created("face" if kind == "face" else "along_edge"),
                 (key, _recall(key, lambda p: _RIP_BOX + "/" + p["feature"]))))
    candidate = {**query, "nearest_to": [256, 4, 20] if kind == "face" else [200, 56, 20]}
    rows += _sheet_edit_rows(key, _RIP_BOX, "rip_face" if kind == "face" else "rip_edge",
                             "RipFeature", None, candidate=candidate, original=query)
    rows += [("doc_close", lambda ctx: {"name": _ctx_get(ctx, "sm_rip", "Rip scratch"),
                "save_changes": False}, _closed_one, None),
             ("doc_activate", lambda ctx: {"name": _ctx_get(ctx, "sm_home", "home")}, "ok", None),
             ("doc_get", {"max_results": 1000}, _story_restored, None)]
    return rows


_SHEET_FLANGE += _rip_edit_story("face") + _rip_edit_story("edge")


def _plastic_rule_read_story():
    """Read one native copied plastic rule in two unit systems without altering its library source."""
    from verify_acts_sketch import _scratch_rows
    rows, write, read, close = _scratch_rows("pr_doc")
    script = (
        "import adsk.core, adsk.fusion, json, math\n"
        "def run(context):\n"
        "    app=adsk.core.Application.get(); d=adsk.fusion.Design.cast(app.activeProduct)\n"
        "    if d is None or app.activeDocument.isSaved or d.timeline.count:\n"
        "        raise RuntimeError('fresh owned unsaved scratch required')\n"
        "    def fields(rule):\n"
        "        return {'thickness':rule.thickness.value, 'radius':rule.nominalRadius.value,\n"
        "                'draft':math.degrees(rule.draftAngle.value),\n"
        "                'minimum':rule.minimumThickness, 'maximum':rule.maximumThickness}\n"
        "    source=d.libraryPlasticRules.item(0); before=fields(source)\n"
        "    rule=d.designPlasticRules.addByCopy(source, 'Sweep Plastic Read')\n"
        "    if rule is None or rule.name!='Sweep Plastic Read':\n"
        "        raise RuntimeError('plastic rule copy did not land')\n"
        "    print(json.dumps({'name':rule.name,'copied':fields(rule),'source':source.name,\n"
        "                      'source_before':before,'source_after':fields(source)}))\n")
    write("sys_execute_script", {"script": script},
          lambda p: p.get("name") == "Sweep Plastic Read" and p.get("source_before") == p.get("source_after"),
          ("pr_baseline", _recall("pr_baseline", lambda p: p)))
    def check(scope, factor, units):
        def verify(p):
            state = p.get("plastic_rules" if scope == "design" else "library_plastic_rules") or {}
            entries = state.get("rules") or []
            expected = _RECALL["pr_baseline"]
            name = expected["name" if scope == "design" else "source"]
            hits = [entry for entry in entries if (entry.get("ref") or {}).get("name") == name]
            values = hits[0] if len(hits) == 1 else {}
            native = expected["copied" if scope == "design" else "source_before"]
            good = (state.get("available") is True and state.get("units") == units
                and state.get("walk_complete") is True and len(hits) == 1
                and values.get("ref", {}).get("scope") == scope
                and _near((values.get("thickness") or {}).get("value"), native["thickness"] * factor, 5e-7)
                and _near((values.get("nominal_radius") or {}).get("value"), native["radius"] * factor, 5e-7)
                and _near((values.get("draft_angle") or {}).get("value_deg"), native["draft"], 5e-7)
                and _near(values.get("minimum_thickness"), native["minimum"] * factor, 5e-7)
                and _near(values.get("maximum_thickness"), native["maximum"] * factor, 5e-7))
            return _measured("scoped plastic rule values and units", state, good)
        return verify
    for units, factor in (("mm", 10), ("in", 1 / 2.54)):
        read("design_get", {"include": ["plastic_rules"], "units": units}, check("design", factor, units))
    read("design_get", lambda ctx: {"include": ["library_plastic_rules"], "units": "mm",
        "name_filter": _RECALL["pr_baseline"]["source"]}, check("library", 10, "mm"))
    close()
    return rows


_SHEET_FLANGE += _plastic_rule_read_story()
