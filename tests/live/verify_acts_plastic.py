# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Plastic and sheet-rule edit stories with independent scoped read-back."""

from verify_core import _RECALL, _measured, _near, _recall, _refused

_RIB_FIXTURE = """import adsk.core, adsk.fusion, json, math
def run(context):
    app=adsk.core.Application.get(); d=adsk.fusion.Design.cast(app.activeProduct)
    if d is None or app.activeDocument.isSaved or d.timeline.count or d.rootComponent.occurrences.count:
        raise RuntimeError('fresh owned unsaved scratch required')
    kind=__KIND__
    comp=d.rootComponent.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
    comp.name='RibWebBench'
    def plane(base, offset):
        if offset == 0: return base
        inp=comp.constructionPlanes.createInput()
        if inp.setByOffset(base,adsk.core.ValueInput.createByReal(offset)) is not True:
            raise RuntimeError('fixture plane refused')
        return comp.constructionPlanes.add(inp)
    def rectangle(lo, hi, operation):
        sk=comp.sketches.add(plane(comp.xYConstructionPlane,lo[2]))
        sk.sketchCurves.sketchLines.addTwoPointRectangle(
            adsk.core.Point3D.create(lo[0],lo[1],0),adsk.core.Point3D.create(hi[0],hi[1],0))
        if sk.profiles.count != 1: raise RuntimeError('fixture rectangle profile count')
        inp=comp.features.extrudeFeatures.createInput(sk.profiles.item(0),operation)
        ext=adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByReal(hi[2]-lo[2]))
        if inp.setOneSideExtent(ext,adsk.fusion.ExtentDirections.PositiveExtentDirection) is not True:
            raise RuntimeError('fixture extrusion refused')
        f=comp.features.extrudeFeatures.add(inp)
        if f is None or f.healthState != adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState:
            raise RuntimeError('fixture extrusion not healthy')
        return f.bodies.item(0)
    target=rectangle([0,0,0],[3,3,.2],adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    rectangle([0,0,.2],[.2,3,2],adsk.fusion.FeatureOperations.JoinFeatureOperation)
    if kind == 'web':
        rectangle([2.8,0,.2],[3,3,2],adsk.fusion.FeatureOperations.JoinFeatureOperation)
    target.name='Base'
    control=rectangle([5,0,0],[6,1,1],adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    control.name='Control'
    expected=2.88 if kind == 'rib' else 3.96
    if comp.bRepBodies.count != 2 or abs(target.volume-expected)>1e-7 or abs(control.volume-1)>1e-7:
        raise RuntimeError('fixture material/count mismatch')
    if kind == 'rib':
        sk=comp.sketches.add(plane(comp.xZConstructionPlane,-1.5))
        a,b=[.2,1.5,1.5],[1.5,1.5,.2]
    else:
        sk=comp.sketches.add(plane(comp.xYConstructionPlane,.8))
        a,b=[.2,1.5,.8],[2.8,1.5,.8]
    sk.name='Guide'
    curve=sk.sketchCurves.sketchLines.addByTwoPoints(
        sk.modelToSketchSpace(adsk.core.Point3D.create(*a)),sk.modelToSketchSpace(adsk.core.Point3D.create(*b)))
    got=[[p.x,p.y,p.z] for p in (curve.startSketchPoint.worldGeometry,curve.endSketchPoint.worldGeometry)]
    if any(abs(got[j][i]-[a,b][j][i])>1e-7 for j in range(2) for i in range(3)):
        raise RuntimeError('fixture guide coordinates mismatch')
    print(json.dumps({'body':target.entityToken,'curves':[curve.entityToken],
        'control':control.entityToken,'component':comp.name,'volume_cm3':target.volume,'guide_cm':got}))
"""


def rib_web_rows():
    """Check healthy Rib/Web material, independent definitions and a retained warning feature."""
    from verify_acts_sketch import _scratch_rows
    result = []
    cases = [("rib_next", "rib", None, True, False, 3049),
             ("rib_distance", "rib", 6, False, False, 3100.61731573),
             ("rib_distance_flip", "rib", 6, True, False, 3028.61731573),
             ("web_next", "web", None, True, False, 4584),
             ("web_extend", "web", None, True, True, 4584),
             ("web_distance", "web", 6, True, False, 4272)]
    cases = [(*case, True, True) for case in cases]
    cases += [("rib_warning", "rib", None, False, False, 3879.75, True, False),
              ("rib_asymmetric_warning", "rib", None, False, False, 3879.75, False, False)]
    for key, kind, depth, flip, extend, volume, symmetric, healthy in cases:
        rows, write, read, close = _scratch_rows(key + "_doc")
        write("sys_execute_script", {"script": _RIB_FIXTURE.replace("__KIND__", repr(kind))},
            lambda p, kind=kind: p.get("component") == "RibWebBench" and bool(p.get("body"))
            and len(p.get("curves") or []) == 1 and bool(p.get("control"))
            and _near(p.get("volume_cm3"), 2.88 if kind == "rib" else 3.96, 1e-7),
            (key + "_fixture", _recall(key + "_fixture", lambda p: p)))
        for role, expected in (("body", 2880 if kind == "rib" else 3960), ("control", 1000)):
            read("model_inspect", lambda ctx, key=key, role=role: {
                "target": _RECALL[key + "_fixture"][role], "include": ["default", "mass"], "units": "mm"},
                lambda p, expected=expected: _near((p.get("mass") or {}).get("volume"), expected, .02))
        def create(ctx, key=key, kind=kind, depth=depth, flip=flip, extend=extend, symmetric=symmetric):
            fixture = _RECALL[key + "_fixture"]
            args = {"kind": kind, "curves": fixture["curves"], "target_body": fixture["body"],
                    "thickness": 2, "symmetric": symmetric, "flip": flip, "extend": extend,
                    "name": "MaterialWitness"}
            if depth is not None:
                args["depth"] = depth
            return args
        write("model_create_rib", create, (lambda p, kind=kind: p.get("kind") == kind
            and p.get("feature") == "MaterialWitness" and p.get("result_bodies") == ["Base"])
            if healthy else _refused("Retained rib 'MaterialWitness'", "Health:", "design_delete_feature"))
        if not healthy:
            def warning(p):
                items = (p.get("timeline") or {}).get("timeline") or []
                hits = [row for row in items if row.get("name") == "MaterialWitness"]
                return _measured("independent retained Rib warning", hits,
                    len(hits) == 1 and hits[0].get("health") == "warning")
            read("design_get", {"include": ["timeline"]}, warning)
        for role, expected in (("body", volume), ("control", 1000)):
            read("model_inspect", lambda ctx, key=key, role=role: {
                "target": _RECALL[key + "_fixture"][role], "include": ["default", "mass"], "units": "mm"},
                lambda p, expected=expected: _measured("independent Rib/Web material", p.get("mass"),
                    _near((p.get("mass") or {}).get("volume"), expected, .02)))
        write("design_edit_timeline", {"action": "roll", "feature": "RibWebBench/MaterialWitness", "to": "before"})
        def definition(p, kind=kind, depth=depth, flip=flip, extend=extend, symmetric=symmetric):
            d = p.get("definition") or {}
            guides = d.get("curves") or []
            return _measured("independent Rib/Web definition", d,
                d.get("type") == ("RibFeature" if kind == "rib" else "WebFeature")
                and _near(d.get("thickness"), 2, 1e-6)
                and (d.get("depth") is None if depth is None else _near(d.get("depth"), depth, 1e-6))
                and d.get("symmetric") is symmetric and d.get("flip") is flip
                and (kind == "rib" or d.get("extend") is extend)
                and d.get("curve_count") == 1 and len(guides) == 1
                and guides[0].get("source_sketch") == "Guide" and d.get("unavailable") == {})
        read("design_get", {"include": ["definition"], "feature": "RibWebBench/MaterialWitness"}, definition)
        write("design_edit_timeline", {"action": "roll", "to": "end"})
        if not healthy:
            write("design_delete_feature", {"feature": "RibWebBench/MaterialWitness"})
            read("model_inspect", lambda ctx, key=key: {"target": _RECALL[key + "_fixture"]["body"],
                "include": ["default", "mass"], "units": "mm"}, lambda p:
                _near((p.get("mass") or {}).get("volume"), 2880, .02))
            read("model_inspect", lambda ctx, key=key: {"target": _RECALL[key + "_fixture"]["control"],
                "include": ["default", "mass"], "units": "mm"}, lambda p:
                _near((p.get("mass") or {}).get("volume"), 1000, .02))
        close()
        result += rows
    return result


def plastic_rule_edit_rows():
    """Copy, update and delete one plastic rule while preserving its library source."""
    from verify_acts_sketch import _scratch_rows
    rows, write, read, close = _scratch_rows("plastic_edit_doc")
    name, renamed = "Sweep Plastic Edit", "Sweep Plastic Renamed"

    def library(p, capture=False):
        state = p.get("library_plastic_rules") or {}
        entries = state.get("rules") or []
        good = (state.get("available") is True and state.get("walk_complete") is True
                and state.get("truncated") is False and len(entries) == 1
                and all(isinstance(entries[0].get(key), (int, float)) for key in
                        ("minimum_thickness", "maximum_thickness", "minimum_draft_angle_deg")))
        if capture and good:
            _RECALL["plastic_edit_library"] = entries[0]
        if not capture:
            good = good and entries[0] == _RECALL["plastic_edit_library"]
        return _measured("independent library source preservation", entries, good)

    read("design_get", {"include": ["library_plastic_rules"], "name_filter": "ABS (1.5mm)"},
         lambda p: library(p, True))
    write("design_edit_plastic_rule", lambda ctx: {"action": "copy",
        "rule": _RECALL["plastic_edit_library"]["ref"], "name": name,
        "minimum_thickness": 1.2, "maximum_thickness": 4.5, "minimum_draft_deg": .5},
        lambda p: p.get("action") == "copy" and p.get("deleted") is False)

    def local(expected_name, low, high, draft, capture=False):
        def check(p):
            state = p.get("plastic_rules") or {}
            entries = state.get("rules") or []
            good = (state.get("available") is True and state.get("walk_complete") is True
                and state.get("truncated") is False and state.get("total") == 1 and len(entries) == 1)
            row = entries[0] if len(entries) == 1 else {}
            source = _RECALL["plastic_edit_library"]
            good = (good and row.get("ref") == {"scope": "design", "index": 0, "name": expected_name}
                and _near(row.get("minimum_thickness"), low, 1e-6)
                and _near(row.get("maximum_thickness"), high, 1e-6)
                and _near(row.get("minimum_draft_angle_deg"), draft, 1e-6)
                and all(row.get(key) == source.get(key) for key in ("thickness", "nominal_radius", "draft_angle")))
            if capture and good:
                _RECALL["plastic_edit_original_ref"] = row["ref"]
            return _measured("independent plastic rule values", row, good)
        return check

    read("design_get", {"include": ["plastic_rules"]}, local(name, 1.2, 4.5, .5, True))
    read("design_get", {"include": ["library_plastic_rules"], "name_filter": "ABS (1.5mm)"}, library)
    write("design_edit_plastic_rule", lambda ctx: {"action": "copy", "rule": _RECALL["plastic_edit_library"]["ref"],
        "name": name.lower()}, _refused("already exists"))
    write("design_edit_plastic_rule", lambda ctx: {"action": "update", "rule": _RECALL["plastic_edit_original_ref"],
        "name": renamed, "minimum_thickness": 1.4, "maximum_thickness": 4.2, "minimum_draft_deg": .75})
    read("design_get", {"include": ["plastic_rules"]}, local(renamed, 1.4, 4.2, .75))
    write("design_edit_plastic_rule", lambda ctx: {"action": "update", "rule": _RECALL["plastic_edit_original_ref"],
        "minimum_thickness": 1.5}, _refused("is now", "re-read"))
    write("design_edit_plastic_rule", lambda ctx: {"action": "update", "rule": _RECALL["plastic_edit_library"]["ref"],
        "minimum_thickness": 1.5}, _refused("library rule"))
    read("design_get", {"include": ["plastic_rules"]}, local(renamed, 1.4, 4.2, .75))
    write("design_edit_plastic_rule", {"action": "delete", "rule": "design:" + renamed},
          lambda p: p.get("deleted") is True)
    read("design_get", {"include": ["plastic_rules"]}, lambda p:
        (p.get("plastic_rules") or {}).get("total") == 0
        and (p.get("plastic_rules") or {}).get("rules") == []
        and (p.get("plastic_rules") or {}).get("walk_complete") is True)
    read("design_get", {"include": ["library_plastic_rules"], "name_filter": "ABS (1.5mm)"}, library)
    close()
    return rows


def sheet_relief_rule_rows():
    """Persist relief choices and scalars only on an unused copy, then verify its deletion."""
    from verify_acts_sketch import _scratch_rows
    rows, write, read, close = _scratch_rows("sheet_relief_doc")
    name = "Sweep Relief Edit"

    def empty_rules(p, capture=False):
        local = p.get("rules") or {}
        library = p.get("library_rules") or {}
        entries = library.get("rules") or []
        good = ((local.get("readable") is False and local.get("rules") is None)
                or (local.get("readable") is True and local.get("total") == 0 and local.get("rules") == []))
        good = good and library.get("readable") is True and library.get("truncated") is False and bool(entries)
        if capture and good:
            _RECALL["sheet_relief_uninitialized"] = {"local": local, "library": library, "ref": entries[0].get("ref")}
            good = _RECALL["sheet_relief_uninitialized"]["ref"] is not None
        elif not capture:
            before = _RECALL["sheet_relief_uninitialized"]
            good = good and local == before["local"] and library == before["library"]
        return _measured("uninitialized sheet data and library preservation", {"local": local, "library": library}, good)

    read("sheet_get", {"include": ["rules", "library_rules"], "max_results": 200}, lambda p: empty_rules(p, True))
    write("sheet_edit_rule", lambda ctx: {"action": "copy", "rule": _RECALL["sheet_relief_uninitialized"]["ref"],
        "name": name}, _refused("model_create_component(sheet_metal=true)", "no copy attempted"))
    read("sheet_get", {"include": ["rules", "library_rules"], "max_results": 200}, empty_rules)
    write("model_create_component", {"name": "ReliefSeed", "sheet_metal": True, "activate": True})

    def library_state(p, capture=False):
        state = p.get("library_rules") or {}
        good = state.get("readable") is True and state.get("truncated") is False
        if capture and good:
            _RECALL["sheet_relief_library_initialized"] = state
        elif not capture:
            good = good and state == _RECALL["sheet_relief_library_initialized"]
        return _measured("library rule source preserved after local edits", state, good)

    read("sheet_get", {"include": ["library_rules"], "max_results": 200}, lambda p: library_state(p, True))

    def census(state, capture=False, removed=False, expected=None):
        entries = state.get("rules") or []
        good = state.get("readable") is True and state.get("truncated") is False
        if capture:
            good = good and len(entries) == 1 and entries[0].get("is_used") is True
            if good:
                _RECALL["sheet_relief_source"] = entries[0]
            return _measured("used sheet rule baseline", entries, good)
        source = _RECALL["sheet_relief_source"]
        originals = [row for row in entries if row.get("name") == source["name"]]
        trials = [row for row in entries if row.get("name") == name]
        good = (good and len(originals) == 1 and originals[0] == source
                and len(entries) == (1 if removed else 2) and state.get("total") == len(entries))
        if removed:
            return _measured("unused sheet rule absent and source preserved", entries, good and not trials)
        trial = trials[0] if len(trials) == 1 else {}
        good = good and len(trials) == 1 and trial.get("is_used") is False
        values = {"reliefWidth": .3, "reliefDepth": .4, "reliefRemnant": .5,
                  "twoBendReliefSize": .6, "threeBendReliefRadius": .7}
        good = good and all(_near((trial.get(key) or {}).get("value_cm"), value, 1e-8)
                            for key, value in values.items())
        if expected:
            good = good and all(trial.get(key) == value for key, value in expected.items())
        return _measured("independent relief rule state and source preservation", trial, good)

    read("sheet_get", {"include": ["rules"]}, lambda p: census(p.get("rules") or {}, True))
    write("sheet_edit_rule", lambda ctx: {"action": "copy", "rule": _RECALL["sheet_relief_uninitialized"]["ref"],
        "name": name, "relief_width": "3 mm", "relief_depth": "4 mm", "relief_remnant": "5 mm",
        "two_bend_relief_size": "6 mm", "three_bend_relief_radius": "7 mm", "relief_shape": "round",
        "two_bend_relief_shape": "round", "two_bend_relief_placement": "tangent", "three_bend_relief_shape": "full_round"})
    initial = {"relief_shape": "round", "two_bend_relief_shape": "round",
               "two_bend_relief_placement": "tangent", "three_bend_relief_shape": "full_round"}
    read("sheet_get", {"include": ["rules"]}, lambda p: census(p.get("rules") or {}, expected=initial))
    write("sheet_edit_rule", {"action": "update", "rule": "design:" + name,
        "relief_width": "9 mm", "two_bend_relief_shape": "square"}, _refused("intersection/vertex", "no edit"))
    read("sheet_get", {"include": ["rules"]}, lambda p: census(p.get("rules") or {}, expected=initial))
    for shape, placement in (("square", "intersection"), ("square", "vertex"), ("round", "tangent")):
        write("sheet_edit_rule", {"action": "update", "rule": "design:" + name,
            "two_bend_relief_shape": shape, "two_bend_relief_placement": placement})
        read("sheet_get", {"include": ["rules"]}, lambda p, shape=shape, placement=placement:
             census(p.get("rules") or {}, expected={**initial, "two_bend_relief_shape": shape, "two_bend_relief_placement": placement}))
    write("sheet_edit_rule", {"action": "update", "rule": "design:" + name,
        "two_bend_relief_placement": "vertex"})
    read("sheet_get", {"include": ["rules"]}, lambda p:
         census(p.get("rules") or {}, expected={**initial, "two_bend_relief_placement": "vertex"}))
    write("sheet_edit_rule", {"action": "update", "rule": "design:" + name,
        "two_bend_relief_shape": "square"})
    read("sheet_get", {"include": ["rules"]}, lambda p:
         census(p.get("rules") or {}, expected={**initial, "two_bend_relief_shape": "square", "two_bend_relief_placement": "vertex"}))
    write("sheet_edit_rule", {"action": "update", "rule": "design:" + name,
        "two_bend_relief_shape": "round", "two_bend_relief_placement": "tangent"})
    read("sheet_get", {"include": ["rules"]}, lambda p: census(p.get("rules") or {}, expected=initial))
    for key, options in (("relief_shape", ("straight", "tear", "round")),
                         ("three_bend_relief_shape", ("none", "intersection", "round_with_radius", "full_round"))):
        for value in options:
            write("sheet_edit_rule", {"action": "update", "rule": "design:" + name, key: value})
            read("sheet_get", {"include": ["rules"]}, lambda p, key=key, value=value:
                 census(p.get("rules") or {}, expected={**initial, key: value}))
    write("sheet_edit_rule", lambda ctx: {"action": "delete", "rule": _RECALL["sheet_relief_source"]["ref"]},
          _refused("used", "unused"))
    read("sheet_get", {"include": ["rules"]}, lambda p: census(p.get("rules") or {}, expected=initial))
    write("sheet_edit_rule", {"action": "delete", "rule": "design:" + name}, lambda p: p.get("deleted") is True)
    read("sheet_get", {"include": ["rules"]}, lambda p: census(p.get("rules") or {}, removed=True))
    read("sheet_get", {"include": ["library_rules"], "max_results": 200}, library_state)
    close()
    return rows
