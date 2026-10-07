# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Bounded live witnesses for remaining surface-boundary feature edits."""

import math

from verify_core import (_RECALL, _ctx_get, _document_closed, _home_address, _home_document,
                         _measured, _new_document, _recall, _refused)


_FIXTURE = r'''import adsk.core, adsk.fusion, json

def run(context):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if (design is None or app.activeDocument.isSaved or design.timeline.count != 0
            or design.rootComponent.bRepBodies.count != 0):
        raise RuntimeError("surface-boundary fixture requires the owned fresh empty scratch")
    root, features = design.rootComponent, design.rootComponent.features
    VR, P = adsk.core.ValueInput.createByReal, adsk.core.Point3D.create
    NEW, CYL = (adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
                adsk.core.SurfaceTypes.CylinderSurfaceType)
    def coll(*entities):
        result = adsk.core.ObjectCollection.create()
        for entity in entities: result.add(entity)
        return result
    def S(sk, x, y, z=0): return sk.modelToSketchSpace(P(x, y, z))
    def center(box):
        return ((box.minPoint.x+box.maxPoint.x)/2, (box.minPoint.y+box.maxPoint.y)/2,
                (box.minPoint.z+box.maxPoint.z)/2)
    def box(name, x, y, w, d, h):
        sk = root.sketches.add(root.xYConstructionPlane); sk.name = name + "_Sketch"
        sk.sketchCurves.sketchLines.addTwoPointRectangle(S(sk, x, y), S(sk, x+w, y+d))
        ext = features.extrudeFeatures.addSimple(sk.profiles.item(0), VR(h), NEW)
        ext.name = name + "_Extrude"; body = ext.bodies.item(0); body.name = name
        return body
    def patch(name, x0, y0, x1, y1):
        sk = root.sketches.add(root.xYConstructionPlane); sk.name = name + "_Sketch"
        sk.sketchCurves.sketchLines.addTwoPointRectangle(S(sk, x0, y0), S(sk, x1, y1))
        feat = features.patchFeatures.add(features.patchFeatures.createInput(sk.profiles.item(0), NEW))
        feat.name = name + "_Patch"; body = feat.bodies.item(0); body.name = name
        return body
    def open_holed_sheet(name, y):
        sk = root.sketches.add(root.xYConstructionPlane); sk.name = name + "_Sketch"
        lines, circles = sk.sketchCurves.sketchLines, sk.sketchCurves.sketchCircles
        width=6 if name == "UntrimCandidate" else 4
        lines.addTwoPointRectangle(S(sk, 0, y), S(sk, width, y+2))
        if name == "UntrimCandidate":
            circles.addByCenterRadius(S(sk, 3, y+1), .7)
        else:
            circles.addByCenterRadius(S(sk, 1, y+1), .4); circles.addByCenterRadius(S(sk, 3, y+1), .5)
        profile = max(sk.profiles, key=lambda item: item.areaProperties().area)
        ext = features.extrudeFeatures.addSimple(profile, VR(.2), NEW)
        plate = ext.bodies.item(0); plate.name = name + "_Plate"
        top = min(plate.faces, key=lambda f: abs(f.centroid.x-width/2)+abs(f.centroid.y-(y+1))+abs(f.centroid.z-.2))
        unstitch = features.unstitchFeatures.add(coll(top), False); unstitch.name = name + "_Unstitch"
        opened_candidates = [b for b in root.bRepBodies if not b.isSolid and b.faces.count == 1
            and abs(center(b.boundingBox)[0]-width/2) < .01
            and abs(center(b.boundingBox)[1]-(y+1)) < .01
            and abs(center(b.boundingBox)[2]-.2) < .01]
        if len(opened_candidates) != 1:
            raise RuntimeError("expected one open sheet at the authored fixture landmark")
        opened = opened_candidates[0]
        opened.name = name + "_Open"
        return opened.faces.item(0)
    # U3 measured geometry for adjacent open patches, a box face split, a holed plate, and both deletes.
    control = box("SurfaceBoundaryControl", 90, 0, 2, 2, 1)
    stitch_a, stitch_b = patch("StitchA", 0, 70, 1, 71), patch("StitchB", 1, 70, 2, 71)
    patch("StitchC", 2, 70, 3, 71); patch("StitchControl", 10, 70, 11, 71)
    si = features.stitchFeatures.createInput(coll(stitch_a, stitch_b), VR(.01), NEW)
    stitch = features.stitchFeatures.add(si); stitch.name = "EditStitch"
    ub = box("UnstitchBox", 0, 80, 2, 2, 1)
    utop = min(ub.faces, key=lambda f: abs(f.centroid.x-1)+abs(f.centroid.y-81)+abs(f.centroid.z-1))
    unstitch = features.unstitchFeatures.add(coll(utop), False); unstitch.name = "EditUnstitch"
    faces = {name: open_holed_sheet(name, y) for name, y in (
        ("UntrimInternal", 50), ("UntrimExternal", 60), ("UntrimManual", 70),
        ("UntrimCandidate", 80))}
    enums = {"all": adsk.fusion.UntrimLoopTypes.AllLoopsUntrimType,
             "external": adsk.fusion.UntrimLoopTypes.ExternalLoopsUntrimType,
             "internal": adsk.fusion.UntrimLoopTypes.InternalLoopsUntrimType}
    for name, mode in (("UntrimInternal", "internal"), ("UntrimExternal", "external")):
        inp = features.untrimFeatures.createInputFromFaces([faces[name]], enums[mode], VR(0))
        feat = features.untrimFeatures.add(inp); feat.name = name
    face = faces["UntrimManual"]
    loops = [loop for loop in face.loops if not loop.isOuter]
    loop = min(loops, key=lambda item: item.boundingBox.minPoint.x)
    manual = features.untrimFeatures.add(features.untrimFeatures.createInputFromLoops([loop]))
    manual.name = "UntrimManual"
    hb = box("DeleteHealBox", 100, 130, 3, 3, 2)
    for name, x, radius in (("HealFilletSmall", 100, .3), ("HealFilletLarge", 103, .5)):
        fi = features.filletFeatures.createInput()
        edge = min(hb.edges, key=lambda e: abs(center(e.boundingBox)[0]-x)
                   + abs(center(e.boundingBox)[1]-130)+abs(center(e.boundingBox)[2]-1))
        fi.edgeSetInputs.addConstantRadiusEdgeSet(coll(edge), VR(radius), True)
        features.filletFeatures.add(fi).name = name
    cyls = [f for f in hb.faces if f.geometry.surfaceType == CYL]
    small = min(cyls, key=lambda f: abs(f.centroid.x-100.15))
    delete_heal = features.deleteFaceFeatures.add(coll(small)); delete_heal.name = "EditDeleteHeal"
    sk = root.sketches.add(root.xYConstructionPlane); sk.name = "DeleteSurfaceSketch"
    pts = [(0, 140), (2, 140), (2, 142)]; curves = adsk.core.ObjectCollection.create()
    previous = S(sk, *pts[0])
    for x, y in pts[1:]:
        line = sk.sketchCurves.sketchLines.addByTwoPoints(previous, S(sk, x, y))
        curves.add(line); previous = line.endSketchPoint
    xi = features.extrudeFeatures.createInput(root.createOpenProfile(curves, False), NEW)
    xi.isSolid = False
    xi.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(VR(1)),
                        adsk.fusion.ExtentDirections.PositiveExtentDirection)
    ext = features.extrudeFeatures.add(xi); ext.name = "DeleteSurfaceExtrude"
    sb = ext.bodies.item(0); sb.name = "DeleteSurfaceBody"
    first = min(sb.faces, key=lambda f: abs(f.centroid.x-1)+abs(f.centroid.y-140)+abs(f.centroid.z-.5))
    delete_surface = features.surfaceDeleteFaceFeatures.add(coll(first)); delete_surface.name = "EditDeleteSurface"
    feature_names = ["EditStitch", "EditUnstitch", "UntrimInternal", "UntrimExternal", "UntrimManual",
                     "EditDeleteHeal", "EditDeleteSurface"]
    actual = []
    for name in feature_names:
        feature = features.itemByName(name)
        if feature is None:
            raise RuntimeError("fixture feature did not resolve: " + name)
        actual.append({"name": feature.name, "type": feature.objectType.rsplit("::", 1)[-1]})
    print(json.dumps({"fixture": "surface-boundary-edit-v1", "control": control.name,
        "features": actual}))
'''


def _save_doc(payload):
    """Save the exact scratch handle returned by doc_new."""
    handle = payload.get("document_handle")
    if not isinstance(handle, str) or not handle:
        raise ValueError("doc_new returned no exact scratch handle")
    return handle


def _fixture(payload):
    """Require the guarded native fixture to create the named surface feature set."""
    report = payload if isinstance(payload, dict) else {}
    wanted = {"EditStitch":"StitchFeature", "EditUnstitch":"UnstitchFeature",
              "UntrimInternal":"UntrimFeature", "UntrimExternal":"UntrimFeature",
              "UntrimManual":"UntrimFeature", "EditDeleteHeal":"DeleteFaceFeature",
              "EditDeleteSurface":"SurfaceDeleteFaceFeature"}
    actual = {row.get("name"): row.get("type") for row in report.get("features", [])
              if isinstance(row, dict)}
    good = (report.get("fixture") == "surface-boundary-edit-v1"
            and actual == wanted and report.get("control") == "SurfaceBoundaryControl")
    return _measured("guarded surface fixture complete", report or payload, good)


def _get_feature(ctx, name):
    """Build a public definition query by its fixture-unique feature name."""
    return {"include": ["definition"], "units": "mm", "feature": name}


def _baseline(key, kind, field):
    """Capture complete public definition and source handles at the feature input marker."""
    def check(payload):
        d = payload.get("definition") or {}
        refs=d.get(field)
        ref_rows=refs if isinstance(refs,list) else [refs]
        refs_readable=(isinstance(refs,(dict,list)) and bool(ref_rows)
                       and all(isinstance(item,dict) and isinstance(item.get("handle"),str)
                               and bool(item.get("handle")) for item in ref_rows))
        good = (d.get("type") == kind and isinstance(d.get("component"), str) and d.get("component")
                and isinstance(d.get("feature_address"), str) and d.get("feature_address")
                and isinstance(d.get("timeline_index"), int) and refs_readable
                and d.get("unavailable")=={}
                and d.get("timeline_index")==_RECALL.get(key.split("_baseline")[0]+"_rolled_index"))
        if kind == "UntrimFeature":
            good = good and d.get("loop_type") in ("all", "external", "internal", "manual")
        if good: _RECALL[key] = d
        return _measured("rolled definition usable", {"type":d.get("type"),"owner":d.get("component"),
            "address":d.get("feature_address"),"index":d.get("timeline_index"),
            "field":d.get(field),"unavailable":d.get("unavailable")}, good)
    return check


def _strip(value):
    """Drop transient handles while retaining descriptor owner and measured geometry."""
    if isinstance(value, dict): return {k:_strip(v) for k,v in value.items() if k not in ("handle","entity_token","token")}
    if isinstance(value, (list,tuple)): return [_strip(v) for v in value]
    return value


def _operand_match(actual, expected):
    """Match one checked public operand using its schema fields instead of token text."""
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return False
    if actual.get("kind") != expected.get("definition_kind"):
        return False
    owner = actual.get("owner") or {}
    if owner.get("component") != expected.get("owner") or owner.get("occurrence") not in (None, ""):
        return False
    geometry = actual.get("geometry") or {}
    if expected.get("name") and actual.get("name") != expected["name"]:
        return False
    if expected.get("area_cm2") is not None:
        area = geometry.get("area")
        if not isinstance(area, (int, float)) or abs(area-expected["area_cm2"]) > 1e-4:
            return False
    if expected.get("volume") is not None:
        volume = geometry.get("volume")
        if not isinstance(volume, (int, float)) or abs(volume-expected["volume"]) > 1e-4:
            return False
    normal=expected.get("normal")
    if normal is not None:
        actual_normal=geometry.get("normal")
        if (not isinstance(actual_normal,list) or len(actual_normal)!=3
                or any(abs(a-b)>0.02 for a,b in zip(actual_normal,normal))):
            return False
    return True


def _changed(key, field, mode=None, candidate_key=None, replace_candidate=False):
    """Check stable feature identity, retained controls, and exact requested operands."""
    def check(payload):
        before = _RECALL.get(key)
        before = before if isinstance(before, dict) and before else {}
        after = payload.get("definition") or {}
        identity = ("feature","component","type","timeline_index","feature_address")
        stable = all(after.get(k)==before.get(k) for k in identity)
        controls = [k for k in before if k not in (field,"supported_edits","unavailable","not_read","note")]
        retained = all(_strip(after.get(k))==_strip(before.get(k)) for k in controls)
        old, new = before.get(field), after.get(field)
        delta = new == mode and mode != old if mode is not None else False
        operand_ok = mode is not None
        if candidate_key:
            expected = _RECALL.get(candidate_key+"_expected")
            old_rows = old if isinstance(old, list) else [old]
            new_rows = new if isinstance(new, list) else [new]
            if expected:
                old_stripped = [_strip(row) for row in old_rows]
                new_stripped = [_strip(row) for row in new_rows]
                pending = list(new_stripped)
                retained_rows = True
                if not replace_candidate:
                    for row in old_stripped:
                        if row not in pending:
                            retained_rows = False
                            break
                        pending.remove(row)
                expected_count = 1 if replace_candidate else len(old_rows)+1
                candidate_rows = [row for row in new_rows if _operand_match(row, expected)]
                operand_ok = (retained_rows and len(new_rows) == expected_count
                              and len(candidate_rows) == 1)
                delta = operand_ok and new != old
        else:
            operand_ok = mode is not None and mode != old
        return _measured("rolled definition changed only requested field", {
            "before":_strip(old),"after":_strip(new),"same_identity":stable,
            "retained_equal":retained,"candidate_matches":operand_ok,
            "unavailable":after.get("unavailable")},
            bool(before) and after.get("unavailable")=={} and stable and retained and delta and operand_ok)
    return check


def _restored(key, field):
    """Require the rolled public definition to equal its captured baseline."""
    def check(payload):
        before = _RECALL.get(key)
        before = before if isinstance(before, dict) and before else {}
        after = payload.get("definition") or {}
        keys=[k for k in before if k not in ("supported_edits","unavailable","not_read","note")]
        same=bool(before) and bool(keys) and after.get("unavailable")=={} and all(
            _strip(after.get(k))==_strip(before.get(k)) for k in keys)
        return _measured("rolled definition restored", {"field":_strip(after.get(field)),
            "feature":after.get("feature"),"owner":after.get("component")}, same)
    return check


def _metric(payload):
    """Capture the published design or body physical-property shape and bounds."""
    mass=payload.get("mass") or {}; rows=mass.get("per_body")
    lo,hi=payload.get("min_point"),payload.get("max_point")
    nums=[mass.get("area"),mass.get("volume")]
    common=(payload.get("units")=="mm" and mass.get("accuracy_used")=="very_high"
            and all(isinstance(x,(int,float)) and math.isfinite(x) for x in nums)
            and isinstance(lo,dict) and isinstance(hi,dict)
            and all(isinstance(p.get(a),(int,float)) and math.isfinite(p[a])
                    for p in (lo,hi) for a in "xyz"))
    if not common:
        return None
    if payload.get("kind")=="body":
        com=mass.get("center_of_mass")
        if (not isinstance(payload.get("target"),str) or not payload["target"]
                or not isinstance(com,list) or len(com)!=3
                or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in com)
                or not isinstance(payload.get("lump_count"),int)):
            return None
        return {"kind":"body","target":payload["target"],"area":nums[0],"volume":nums[1],
                "lump_count":payload["lump_count"],"center":com,
                "min":[lo[a] for a in "xyz"],"max":[hi[a] for a in "xyz"]}
    if (payload.get("kind")!="design" or mass.get("per_body_truncated") is not False
            or not isinstance(rows,list) or mass.get("per_body_count")!=len(rows) or not rows
            or any(not isinstance(r.get("body"),str) or type(r.get("is_solid")) is not bool
                   or (r.get("is_solid") is True and r.get("volume") is None) for r in rows)):
        return None
    shapes=[(r["is_solid"],r.get("volume"),r.get("lump_count")) for r in rows]
    return {"area":nums[0],"volume":nums[1],"rows":sorted((r["body"],*shape) for r,shape in zip(rows,shapes)),
            "shapes":sorted(shapes,key=repr),"min":[lo[a] for a in "xyz"],"max":[hi[a] for a in "xyz"]}


def _capture(key,label):
    """Save a complete independent public geometry census."""
    def check(payload):
        value=_metric(payload)
        if value is not None: _RECALL[key]=value
        return _measured(label+" independent geometry baseline",value or payload,value is not None)
    return check


def _changed_metric(key,label):
    """Require an independent area, volume, body-row, or envelope effect."""
    def check(payload):
        a,b=_RECALL.get(key),_metric(payload)
        if a is not None and b is not None and a.get("kind")=="body" and b.get("kind")=="body":
            good=(a["target"]==b["target"] and (a["lump_count"]!=b["lump_count"]
                  or abs(a["area"]-b["area"])>1e-5 or abs(a["volume"]-b["volume"])>1e-5
                  or any(abs(x-y)>1e-4 for x,y in zip(a["center"]+a["min"]+a["max"],
                                                       b["center"]+b["min"]+b["max"]))))
        else:
            good=(a is not None and b is not None and a.get("kind","design")==b.get("kind","design")
                  and (a["shapes"]!=b["shapes"] or abs(a["area"]-b["area"])>1e-5
                       or abs(a["volume"]-b["volume"])>1e-5
                       or any(abs(x-y)>1e-4 for x,y in zip(a["min"]+a["max"],b["min"]+b["max"]))))
        return _measured(label+" independent effect",b or payload,good)
    return check


def _same_metric(key,label):
    """Require the complete public geometry census restored to the saved baseline."""
    def check(payload):
        a,b=_RECALL.get(key),_metric(payload)
        if a is not None and b is not None and a.get("kind")=="body" and b.get("kind")=="body":
            good=(a["target"]==b["target"] and a["lump_count"]==b["lump_count"]
                  and abs(a["area"]-b["area"])<=1e-5 and abs(a["volume"]-b["volume"])<=1e-5
                  and all(abs(x-y)<=1e-4 for x,y in zip(a["center"]+a["min"]+a["max"],
                                                       b["center"]+b["min"]+b["max"])))
        else:
            good=(a is not None and b is not None and a.get("kind","design")==b.get("kind","design")
                  and a["shapes"]==b["shapes"] and abs(a["area"]-b["area"])<=1e-5
                  and abs(a["volume"]-b["volume"])<=1e-5
                  and all(abs(x-y)<=1e-4 for x,y in zip(a["min"]+a["max"],b["min"]+b["max"])))
        return _measured(label+" independent geometry restored",b or payload,good)
    return check


def _scratch_active(payload):
    """Require the owned scratch to remain active through its last edit read."""
    active=payload.get("active") or {}
    return _measured("owned surface scratch active",active,
                     active.get("document_handle")==_RECALL.get("surface_doc") and payload.get("open_count",0)>=2)


def _timeline_end(payload):
    """Require the exact end marker and complete explicit healthy timeline summary."""
    t=payload.get("timeline") or {}; rows=t.get("timeline"); summary=t.get("summary")
    states=summary.get("states") if isinstance(summary,dict) else None
    exceptions=summary.get("exceptions") if isinstance(summary,dict) else None
    good=(isinstance(rows,list) and t.get("returned")==t.get("count")==len(rows)
          and t.get("marker_position")==t.get("count") and t.get("truncated") is not True
          and states=={"healthy":len(rows)} and exceptions==[])
    return _measured("complete healthy timeline at end",t,good)


def _roll(ctx,feature,to):
    """Build one explicit timeline roll request."""
    return {"action":"roll","feature":feature,"to":to}


def _roll_check(to, feature=None):
    """Require one exact timeline roll response."""
    def check(payload):
        good=payload.get("rolled") is True and payload.get("to")==to
        if to=="end": good=good and payload.get("marker_position")==payload.get("timeline_count")
        if to=="before" and feature and isinstance(payload.get("marker_position"),int):
            _RECALL[feature+"_rolled_index"]=payload["marker_position"]
        return _measured("timeline marker moved "+to,payload,good)
    return check


def _owned(ctx, args):
    """Pin a scratch write to this act's exact owned document."""
    return {**args,"expect_document":_ctx_get(ctx,"surface_doc","owned scratch")}


def _edit_args(case, action, field, mode=None, ctx=None, candidate_key=None, restore=False,
               replace_candidate=False):
    """Build the public edit or exact baseline restore from the captured definition."""
    d=_RECALL.get(case+"_baseline") or {}; refs=d.get(field)
    args={"feature":d.get("feature_address",""),"action":action}
    args["expect_document"]=_ctx_get(ctx,"surface_doc","owned scratch")
    if mode is not None: args["mode"]=d.get(field.replace("faces_to_untrim","loop_type")) if restore else mode
    if isinstance(refs,(dict,list)):
        items=refs if isinstance(refs,list) else [refs]
        handles=[x.get("handle") for x in items if isinstance(x,dict)]
        if candidate_key and not restore:
            candidate_handle=_ctx_get(ctx,candidate_key,"typed surface candidate")
            handles=[candidate_handle] if replace_candidate else handles+[candidate_handle]
        args["references"]=handles
    return args


def _setter_result(case, changed=True):
    """Require a truthful feature edit response and retained owner identity."""
    def check(payload):
        before=_RECALL.get(case.replace(" restore", "")+"_baseline")
        before=before if isinstance(before,dict) and before else {}
        good=(bool(before) and payload.get("edited") is True and payload.get("definition_matches") is True
              and payload.get("same_feature") is True and payload.get("owner_matches") is True
              and payload.get("marker_restored") is True and isinstance(payload.get("feature_health"),dict)
              and payload.get("new_timeline_errors")==[] and payload.get("new_timeline_warnings")==[])
        if changed: good=good and payload.get("geometry_changed") is True
        return _measured(case+" public edit readback",{"edited":payload.get("edited"),
            "definition_matches":payload.get("definition_matches"),"same_feature":payload.get("same_feature"),
            "owner_matches":payload.get("owner_matches"),"geometry_changed":payload.get("geometry_changed"),
            "feature_health":payload.get("feature_health"),"new_timeline_errors":payload.get("new_timeline_errors"),
            "new_timeline_warnings":payload.get("new_timeline_warnings")},good)
    return check


def _candidate_body_metric(name, key):
    """Bank the independently inspected physical shape of the exact candidate body."""
    def check(payload):
        result=_capture(name+"_candidate_body","candidate body")(payload)
        expected=_RECALL.get(key+"_expected")
        value=_RECALL.get(name+"_candidate_body")
        if result and expected and value and value.get("kind")=="body":
            expected["area_cm2"]=value["area"]/100.0
            expected["volume"]=value["volume"]/1000.0
        return result
    return check


def _candidate(kind, point, key, baseline_key):
    """Require a complete scoped census and bank one exact typed candidate descriptor."""
    def check(payload):
        baseline=_RECALL.get(baseline_key)
        owner=baseline.get("component") if isinstance(baseline,dict) else None
        matches=payload.get("matches")
        returned=payload.get("returned")
        count=payload.get("match_count")
        complete=(isinstance(matches,list) and returned==len(matches)==count
                  and payload.get("truncated") is not True)
        near=[]
        if complete:
            near=[row for row in matches if row.get("kind")==kind
                  and isinstance(row.get("position"),list) and len(row["position"])==3
                  and all(isinstance(v,(int,float)) and math.isfinite(v) and abs(v-w)<=1.0
                          for v,w in zip(row["position"],point))]
        row=near[0] if len(near)==1 else {}
        good=(complete and len(near)==1 and bool(row.get("handle")) and bool(owner)
              and isinstance(row.get("area"),(int,float)) and math.isfinite(row["area"]))
        if good:
            expected={"definition_kind":"face","owner":owner,"area_cm2":row["area"]/100.0}
            normal=row.get("normal")
            if kind=="planar_face" and isinstance(normal,list) and len(normal)==3:
                expected["normal"]=normal
            _RECALL[key+"_expected"]=expected
        return _measured("one typed candidate at the fixture landmark",{"returned":returned,
            "match_count":count,"kind":row.get("kind"),"position":row.get("position"),
            "area":row.get("area")},good)
    return check


def _owned_body_candidate(name, key, expected_solid=None):
    """Require one exact named visible root body and bank its owner and shape."""
    def check(payload):
        tree=payload.get("tree") or {}; bodies=tree.get("root_bodies") or []
        found=[row for row in bodies if row.get("name")==name]
        row=found[0] if len(found)==1 else {}
        good=(tree.get("truncated") is False and tree.get("children_truncated") is False
              and tree.get("root_bodies_truncated") is not True
              and len(found)==1 and row.get("visible") is True
              and (expected_solid is None or row.get("is_solid") is expected_solid)
              and isinstance(row.get("handle"),str) and bool(row["handle"])
              and isinstance(tree.get("root"),str) and bool(tree["root"]))
        if good:
            _RECALL[key+"_expected"]={"definition_kind":"entity","owner":tree["root"],
                "name":name,"surface_type":None}
        return _measured("one exact root surface body handle",{"root":tree.get("root"),
            "matches":found,"root_bodies_truncated":tree.get("root_bodies_truncated")},good)
    return check


def _surface_body_candidate(name, key):
    """Require one exact named root surface body and bank its owner and shape."""
    return _owned_body_candidate(name, key, expected_solid=False)


def _edit_transition(rows, name, field, action, kind, mode=None, desired=None, candidate=None,
                     desired_field=None, replace_candidate=False, local_target=None,
                     changed=True):
    """Append a rolled definition read, one edit, an independent effect read, and exact restore."""
    baseline=name+"_baseline"; metric=name+"_metric"; feature=name
    result_field=desired_field or field
    rows += [("design_edit_timeline",lambda c,f=feature:_owned(c,_roll(c,f,"before")),_roll_check("before",feature),None),
             ("design_get",lambda c,f=feature:{"include":["definition"],"units":"mm","feature":f},
              _baseline(baseline,kind,field),None),
             ("design_edit_timeline",lambda c:_owned(c,{"action":"roll","to":"end"}),_roll_check("end"),None),
             ("model_inspect",{"target":"","include":["default","mass"],"units":"mm","accuracy":"very_high","per_body":True},_capture(metric,name+" baseline"),None),
             ("model_inspect",{"target":"SurfaceBoundaryControl","include":["default","mass"],"units":"mm","accuracy":"very_high","per_body":True},_capture(name+"_control",name+" control"),None)]
    candidate_key=None
    if candidate and candidate[1]=="surface_body":
        body, _kind, _point=candidate; candidate_key=name+"_candidate"
        rows.append(("design_get",{"include":["tree"],"tree_bodies":True,"tree_handles":True,
            "max_depth":1,"max_results":200},_surface_body_candidate(body,candidate_key),
            (candidate_key,lambda p:next(row["handle"] for row in p["tree"]["root_bodies"]
                                          if row.get("name")==body))))
        rows.append(("model_inspect",{"target":body,"include":["default","mass"],"units":"mm",
            "accuracy":"very_high","per_body":True},_candidate_body_metric(name,candidate_key),None))
    elif candidate:
        body, qkind, point = candidate; candidate_key=name+"_candidate"
        expected_solid = body == "DeleteHealBox"
        rows.append(("design_get",{"include":["tree"],"tree_bodies":True,"tree_handles":True,
            "max_depth":1,"max_results":200},_owned_body_candidate(body,candidate_key,expected_solid),
            (name+"_body_handle",lambda p:next(row["handle"] for row in p["tree"]["root_bodies"]
                                                if row.get("name")==body))))
        rows.append(("model_inspect",{"target":body,"include":["default","mass"],"units":"mm",
            "accuracy":"very_high","per_body":True},_candidate_body_metric(name,candidate_key),None))
        rows.append(("find_geometry",lambda c,b=body,k=qkind,p=point,feature_key=name:{"target":_ctx_get(c,feature_key+"_body_handle","typed surface body"),
            "kind":k,"nearest_to":p,"units":"mm","max_results":200},
            _candidate(qkind,point,candidate_key,baseline),
            (candidate_key,lambda p:next(row["handle"] for row in p["matches"]
                if row.get("kind")==qkind and all(abs(v-w)<=1.0 for v,w in zip(row.get("position",[]),point))))))
    local_key=name+"_local"
    if local_target:
        rows.append(("model_inspect",{"target":local_target,"include":["default","mass"],"units":"mm","accuracy":"very_high","per_body":True},_capture(local_key,name+" local baseline"),None))
    rows += [("model_edit_feature",lambda c,n=name,f=field,a=action,m=mode,ck=candidate_key,rep=replace_candidate:_edit_args(n,a,f,m,c,ck,replace_candidate=rep),
              _setter_result(name, changed),None),
             ("design_edit_timeline",lambda c,f=feature:_owned(c,_roll(c,f,"before")),_roll_check("before",feature),None),
             ("design_get",lambda c,f=feature:{"include":["definition"],"units":"mm","feature":f},
              _changed(baseline,result_field,desired,candidate_key,replace_candidate),None),
             ("design_edit_timeline",lambda c:_owned(c,{"action":"roll","to":"end"}),_roll_check("end"),None),
             ("model_inspect",{"target":"","include":["default","mass"],"units":"mm","accuracy":"very_high","per_body":True},(_changed_metric if changed else _same_metric)(metric,name+" changed"),None),
             ("model_inspect",{"target":"SurfaceBoundaryControl","include":["default","mass"],"units":"mm","accuracy":"very_high","per_body":True},_same_metric(name+"_control",name+" changed control"),None)]
    if local_target:
        rows.append(("model_inspect",{"target":local_target,"include":["default","mass"],"units":"mm","accuracy":"very_high","per_body":True},_changed_metric(local_key,name+" local changed"),None))
    rows += [("model_edit_feature",lambda c,n=name,f=field,a=action,m=mode:_edit_args(n,a,f,m,ctx=c,restore=True),
              _setter_result(name+" restore",False),None),
             ("design_edit_timeline",lambda c,f=feature:_owned(c,_roll(c,f,"before")),_roll_check("before",feature),None),
             ("design_get",lambda c,f=feature:{"include":["definition"],"units":"mm","feature":f},
              _restored(baseline,result_field),None),
             ("design_edit_timeline",lambda c:_owned(c,{"action":"roll","to":"end"}),_roll_check("end"),None),
             ("model_inspect",{"target":"","include":["default","mass"],"units":"mm","accuracy":"very_high","per_body":True},_same_metric(metric,name+" restored"),None),
             ("model_inspect",{"target":"SurfaceBoundaryControl","include":["default","mass"],"units":"mm","accuracy":"very_high","per_body":True},_same_metric(name+"_control",name+" restored control"),None),
             ("design_get",{"include":["timeline"],"max_results":2000},_timeline_end,None)]
    if local_target:
        rows.insert(len(rows)-1,("model_inspect",{"target":local_target,"include":["default","mass"],"units":"mm","accuracy":"very_high","per_body":True},_same_metric(local_key,name+" local restored"),None))


def _manual_refusal(rows):
    """Check the manual-Untrim refusal without mutating its measured baseline."""
    name="UntrimManual"; field="faces_to_untrim"
    rows += [("design_edit_timeline",lambda c:_owned(c,_roll(c,name,"before")),_roll_check("before",name),None),
             ("design_get",{"include":["definition"],"units":"mm","feature":name},
              _baseline(name+"_baseline","UntrimFeature",field),None),
             ("design_edit_timeline",lambda c:_owned(c,{"action":"roll","to":"end"}),_roll_check("end"),None),
             ("model_inspect",{"target":"","include":["default","mass"],"units":"mm","accuracy":"very_high","per_body":True},_capture("manual_metric","manual baseline"),None),
             ("model_inspect",{"target":"SurfaceBoundaryControl","include":["default","mass"],"units":"mm","accuracy":"very_high","per_body":True},_capture("manual_control","manual control"),None),
             ("model_edit_feature",lambda c:_edit_args(name,"boundary",field,"all",c),
              _refused("existing manual Untrim loop selection"),None),
             ("model_inspect",{"target":"","include":["default","mass"],"units":"mm","accuracy":"very_high","per_body":True},_same_metric("manual_metric","manual refusal"),None),
             ("model_inspect",{"target":"SurfaceBoundaryControl","include":["default","mass"],"units":"mm","accuracy":"very_high","per_body":True},_same_metric("manual_control","manual refusal control"),None),
             ("design_get",{"include":["timeline"],"max_results":2000},_timeline_end,None)]


def surface_boundary_edit_rows():
    """Return bounded witnesses for Untrim modes, Stitch/Unstitch inputs, and both DeleteFace forms."""
    rows=[("doc_get",{},_home_document,("surface_home",_recall("surface_home",_home_address))),
          ("doc_new",lambda c:{"expect_document":_ctx_get(c,"surface_home","original document")},
           _new_document,("surface_doc",_recall("surface_doc",_save_doc))),
          ("sys_execute_script",lambda c:{"script":_FIXTURE,"read_only":False,
              "expect_document":_ctx_get(c,"surface_doc","owned scratch")},_fixture,None),
          ("design_get",{"include":["timeline"],"max_results":2000},_timeline_end,None)]
    _manual_refusal(rows)
    # Only Untrim internal has retained successful setter/effect evidence; other choices stay explicit discriminators.
    _edit_transition(rows,"UntrimInternal","faces_to_untrim","boundary","UntrimFeature",mode="all",
                     desired="all",desired_field="loop_type",changed=False)
    _edit_transition(rows,"UntrimInternal","faces_to_untrim","boundary","UntrimFeature",mode="external",
                     desired="external",desired_field="loop_type")
    _edit_transition(rows,"UntrimExternal","faces_to_untrim","boundary","UntrimFeature",mode="internal",
                     desired="internal",desired_field="loop_type")
    _edit_transition(rows,"UntrimInternal","faces_to_untrim","boundary","UntrimFeature",mode="internal",
                     candidate=("UntrimCandidate_Open","planar_face",[30.0,810.0,2.0]),
                     desired_field="faces_to_untrim",replace_candidate=True)
    _edit_transition(rows,"EditStitch","stitch_surfaces","inputs","StitchFeature",
                     candidate=("StitchC","surface_body",None))
    _edit_transition(rows,"EditUnstitch","input_faces","inputs","UnstitchFeature",
                     candidate=("UnstitchBox","planar_face",[0.0,810.0,5.0]))
    _edit_transition(rows,"EditDeleteHeal","deleted_faces","inputs","DeleteFaceFeature",
                     candidate=("DeleteHealBox","cylinder_face",[1027.5,1302.5,10.0]))
    _edit_transition(rows,"EditDeleteSurface","deleted_faces","inputs","SurfaceDeleteFaceFeature",
                     candidate=("DeleteSurfaceBody","planar_face",[20.0,1410.0,5.0]),
                     replace_candidate=True, local_target="DeleteSurfaceBody")
    rows += [("doc_get",{},_scratch_active,None),
             ("doc_activate",lambda c:{"name":_ctx_get(c,"surface_home","original document"),
                 "expect_document":_ctx_get(c,"surface_doc","owned scratch")},"ok",None),
             ("doc_get",{},lambda p:_measured("original document active",p.get("active"),
                 (p.get("active") or {}).get("document_handle")==_RECALL.get("surface_home")),None),
             ("doc_close",lambda c:{"name":_ctx_get(c,"surface_doc","owned scratch"),"save_changes":False,
                 "expect_document":_ctx_get(c,"surface_home","original document")},_document_closed,None),
             ("doc_get",{},_home_document,None)]
    return rows
