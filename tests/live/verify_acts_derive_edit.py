# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""DeriveFeature edits on one host derived from a retained saved source."""

from cloud_config import FOLDER, PROJECT
from verify_acts_cloud import _STAMP, _derived, _file_settled, _parameter_table, _saved_as, _settled
from verify_core import (
    _RECALL, _activated, _document_closed, _extruded, _home_address, _home_document, _measured,
    _near, _new_document, _recall, _refused)

_LISTING = {"include_model_parameters": True}
_INSPECT = {"include": ["default", "mass"], "units": "mm", "accuracy": "very_high",
            "per_body": True}
_FAVORITE, _DEPENDENT = "DeriveEditFav", "DeriveEditDep"


def _names(p):
    """param_get: every listed parameter by name with its expression and value, or None when partial."""
    table = _parameter_table(p)
    if table is None:
        return None
    return {name: (row["expression"], row["value"])
            for group in ("user", "model") for name, row in table[group].items()}


def _bodies(count, volume):
    """model_inspect over the host: body count and total volume."""
    def check(p):
        mass = p.get("mass") or {}
        return _measured("host body census", {"bodies": mass.get("per_body_count"),
                                              "volume": mass.get("volume")},
                         p.get("kind") == "design" and mass.get("per_body_count") == count
                         and mass.get("per_body_truncated") is False
                         and _near(mass.get("volume"), volume, 0.01))
    return check


def _timeline_ok(p):
    """design_get timeline: every row healthy, the marker at the end, the rows by index."""
    timeline = p.get("timeline") or {}
    summary = timeline.get("summary") or {}
    count = timeline.get("count")
    return _measured("timeline healthy with the marker at its end",
                     {"count": count, "marker": timeline.get("marker_position"),
                      "states": summary.get("states")},
                     isinstance(count, int) and count > 0 and timeline.get("returned") == count
                     and timeline.get("marker_position") == count
                     and summary.get("states") == {"healthy": count}
                     and summary.get("exceptions") == [])


def _toggled(include, check):
    """The favourites reply: flag before and after, an unmoved marker, no new health rows."""
    def judge(p):
        health = p.get("health_after") or {}
        return _measured(
            f"favourites {'on' if include else 'off'} reply",
            {key: p.get(key) for key in ("edited", "favorite_parameters_before",
                                         "favorite_parameters_after", "parameters_disappeared",
                                         "parameters_appeared", "became_local", "same_feature")},
            p.get("action") == "mode" and p.get("edited") is True
            and p.get("favorite_parameters_before") is (not include)
            and p.get("favorite_parameters_after") is include and p.get("same_feature") is True
            and p.get("marker_before") == p.get("marker_after")
            and health.get("errors") == [] and p.get("recomputed") is True
            and p.get("body_count_before") == p.get("body_count_after") == 2
            and p.get("bodies_arrived") == p.get("bodies_left") == p.get("bodies_changed") == []
            and "restor" not in (p.get("note") or "").lower() and check(p))
    return judge


def _sources(names_key, arrived, left):
    """The source-replacement reply: the listed names, what arrived and left, a healthy timeline."""
    def judge(p):
        want = sorted(_RECALL[key] for key in names_key)
        return _measured(
            "source replacement reply",
            {key: p.get(key) for key in ("edited", "source_entities_after", "bodies_arrived",
                                         "bodies_left", "new_timeline_errors", "same_feature")},
            p.get("action") == "inputs" and p.get("edited") is True and p.get("answered") is True
            and p.get("source_entities_after") == want
            and p.get("source_identity_verified") is True and p.get("same_feature") is True
            and len(p.get("bodies_arrived") or []) == arrived
            and len(p.get("bodies_left") or []) == left
            and p.get("new_timeline_errors") == [] and p.get("out_of_date") is False
            and p.get("marker_before") == p.get("marker_after"))
    return judge


def _derive_edit_rows():
    """Favourites off and on, source replacement, rolled-marker refusals, then the link break."""
    name = "SweepDeriveEdit." + _STAMP
    rows = [("doc_get", {}, _home_document, ("de_home", _recall("de_home", _home_address))),
            ("doc_new", lambda c: {"expect_document": c["de_home"]}, _new_document,
             ("de_source", _recall("de_source", lambda p: p["document_handle"])))]

    def write(tool, args, check="ok", save=None, owner="de_host"):
        rows.append((tool, lambda c, args=args, owner=owner: {
            **(args(c) if callable(args) else args), "expect_document": c[owner]}, check, save))

    def read(tool, args, check, save=None):
        rows.append((tool, args, check, save))

    def edit(action, check, **extra):
        write("model_edit_feature", lambda c: {
            "feature": c["de_feature"], "action": action,
            **{key: (value(c) if callable(value) else value) for key, value in extra.items()}},
            check)

    def table_holds(label, judge, park=None):
        def check(p):
            names = _names(p)
            if park and names is not None:
                _RECALL[park] = names
            return _measured(label, names, names is not None and judge(names))
        read("param_get", _LISTING, check)

    derived = lambda: _RECALL.get("de_derived")
    fresh = lambda: _RECALL.get("de_fresh")

    def source_box(sketch, x, height, key):
        write("sketch_create", {"plane": "xy", "name": sketch}, owner="de_source")
        write("sketch_add_geometry", {"sketch_name": sketch, "geometry": [
            {"kind": "rectangle", "x1": x, "y1": 0, "x2": x + 10, "y2": 10}]}, owner="de_source")
        write("model_extrude", {"sketch_name": sketch, "distance": height, "operation": "new"},
              lambda p: _extruded(p) and len(p.get("result_bodies") or []) == 1,
              (key, _recall(key, lambda p: p["result_bodies"][0])), owner="de_source")

    write("param_add", {"name": _FAVORITE, "expression": "7 mm", "unit": "mm", "favorite": True},
          lambda p: p.get("added") is True and p.get("favorite") is True, owner="de_source")
    source_box("DeriveEditA", 0, 10, "de_a")
    source_box("DeriveEditB", 20, 20, "de_b")
    write("doc_save_as", {"name": name, "project": PROJECT, "folder": FOLDER},
          _saved_as(name, FOLDER),
          owner="de_source")
    rows.extend(_settled(name, "de_urn"))
    read("data_get", lambda c: {"file": c["de_urn"]},
         _file_settled(FOLDER, file_key="de_urn", file_name=name))
    write("doc_new", {}, _new_document, ("de_host", _recall("de_host", lambda p: p["document_handle"])),
          owner="de_source")
    write("doc_insert_derive", lambda c: {
        "document_id": c["de_urn"], "source_bodies": [c["de_a"]], "include_parameters": False,
        "include_favorite_parameters": True},
        lambda p: _derived(name)(p) and p.get("bodies_landed") == 1
        and len(p.get("imported_parameter_names") or []) == 1,
        ("de_feature", _recall("de_feature", lambda p: p["feature_name"])))
    table_holds("the host lists the one derived favourite at 7 mm",
                lambda names: len(names) == 1 and _near(next(iter(names.values()))[1], 7, 1e-9))
    read("param_get", _LISTING, lambda p: len(_names(p) or {}) == 1,
         ("de_derived", _recall("de_derived", lambda p: next(iter(_names(p))))))
    write("sketch_create", {"plane": "xy", "name": "DeriveEditHost"})
    write("sketch_add_geometry", {"sketch_name": "DeriveEditHost", "geometry": [
        {"kind": "rectangle", "x1": 100, "y1": 0, "x2": 110, "y2": 10}]})
    write("model_extrude", {"sketch_name": "DeriveEditHost", "distance": 5, "operation": "new"},
          lambda p: _extruded(p) and len(p.get("result_bodies") or []) == 1)
    read("model_inspect", _INSPECT, _bodies(2, 1500))
    read("design_get", lambda c: {"include": ["definition"], "feature": c["de_feature"]},
         lambda p: _measured("the derive definition and its three edits", p.get("definition"),
                             (p.get("definition") or {}).get("source_entities") == [_RECALL["de_a"]]
                             and (p.get("definition") or {}).get("include_favorite_parameters") is True
                             and (p.get("definition") or {}).get("derived_parameters") == [derived()]
                             and [row.get("action") for row in
                                  (p.get("definition") or {}).get("supported_edits") or []]
                             == ["inputs", "mode", "break_link"]))

    # 1. favourites off with nothing depending on the derived parameter.
    edit("mode", _toggled(False, lambda p: p.get("parameters_disappeared") == [derived()]
                          and p.get("became_local") == []), mode="favourites_off")
    table_holds("the derived name is gone", lambda names: derived() not in names)
    read("model_inspect", _INSPECT, _bodies(2, 1500))
    read("design_get", {"include": ["timeline"], "max_results": 100}, _timeline_ok)

    # 2. favourites on: the same name back at its value.
    edit("mode", _toggled(True, lambda p: p.get("parameters_appeared") == [
        {"name": derived(), "derived": True}]), mode="favourites_on")
    table_holds("the derived name is back at 7 mm",
                lambda names: derived() in names and _near(names[derived()][1], 7, 1e-9))

    # 3. favourites off under a local dependent.
    write("param_add", lambda c: {"name": _DEPENDENT, "expression": f"{derived()} * 2",
                                  "unit": "mm"}, lambda p: p.get("added") is True)
    dependent = lambda names: (names.get(_DEPENDENT, (None, None))[0] == f"{derived()} * 2"
                               and _near(names[_DEPENDENT][1], 14, 1e-9))
    edit("mode", _toggled(False, lambda p: p.get("became_local") == [
        {"name": derived(), "dependents": [_DEPENDENT]}]
        and p.get("parameters_disappeared") == []
        and "no longer derived" in (p.get("note") or "")), mode="favourites_off")
    table_holds("the once-derived name stays at 7 mm under its dependent",
                lambda names: derived() in names and _near(names[derived()][1], 7, 1e-9)
                and dependent(names), park="de_local_table")

    # 4. favourites on after that: a new derived name beside the local one.
    def new_name(p):
        appeared = p.get("parameters_appeared") or []
        good = (len(appeared) == 1 and appeared[0].get("derived") is True
                and appeared[0].get("name") not in _RECALL["de_local_table"])
        if good:
            _RECALL["de_fresh"] = appeared[0]["name"]
        return good and p.get("became_local") == []
    edit("mode", _toggled(True, new_name), mode="favourites_on")
    table_holds("a new derived name beside the local one",
                lambda names: fresh() in names and fresh() != derived() and derived() in names
                and _near(names[fresh()][1], 7, 1e-9) and dependent(names)
                and len(names) == len(_RECALL["de_local_table"]) + 1, park="de_table")

    # 5. already as requested.
    edit("mode", lambda p: _measured("nothing written", {"edited": p.get("edited")},
                                     p.get("edited") is False
                                     and "nothing was written" in (p.get("note") or "")),
         mode="favourites_on")
    table_holds("the parameters are unchanged", lambda names: names == _RECALL["de_table"])

    # 6. source replacement, and a name the source does not hold.
    edit("inputs", _sources(("de_a", "de_b"), 1, 0),
         references=lambda c: [c["de_a"], c["de_b"]])
    read("model_inspect", _INSPECT, _bodies(3, 3500))
    read("design_get", lambda c: {"include": ["definition"], "feature": c["de_feature"]},
         lambda p: (p.get("definition") or {}).get("source_entities")
         == sorted([_RECALL["de_a"], _RECALL["de_b"]]))
    table_holds("the parameters are unchanged", lambda names: names == _RECALL["de_table"])
    edit("inputs", _sources(("de_a",), 0, 1), references=lambda c: [c["de_a"]])
    read("model_inspect", _INSPECT, _bodies(2, 1500))
    edit("inputs", _refused("matches 0 root bodies", "The source offers"),
         references=["DeriveEditNoSuchBody"])
    read("model_inspect", _INSPECT, _bodies(2, 1500))
    read("design_get", {"include": ["timeline"], "max_results": 100}, _timeline_ok)

    # 8. marker not at the end: every action refused, nothing changed.
    write("design_edit_timeline", {"action": "roll", "to": "previous"},
          lambda p: p.get("rolled") is True and p.get("rolled_back") == 1)
    rolled = _refused("roll it to the end", "design_edit_timeline")
    edit("mode", rolled, mode="favourites_off")
    edit("inputs", rolled, references=lambda c: [c["de_a"], c["de_b"]])
    edit("break_link", rolled)
    write("design_edit_timeline", {"action": "roll", "to": "end"},
          lambda p: p.get("rolled") is True and p.get("rolled_back") == 0)
    read("model_inspect", _INSPECT, _bodies(2, 1500))
    table_holds("the parameters are unchanged", lambda names: names == _RECALL["de_table"])
    read("design_get", {"include": ["timeline"], "max_results": 100}, _timeline_ok)

    # 7. break the link, last.
    read("doc_get", {"include": ["default", "xref_tree"]},
         lambda p: p["xref_tree"].get("walk_complete") is True
         and p["xref_tree"].get("reference_link_count") == 1)
    edit("break_link", lambda p: _measured(
        "link break reply", {key: p.get(key) for key in (
            "edited", "replaced", "same_feature", "kind_before", "kind_after",
            "parameters_disappeared", "bodies_left", "bodies_changed", "new_timeline_errors")},
        p.get("action") == "break_link" and p.get("edited") is True and p.get("replaced") is True
        and p.get("same_feature") is False and p.get("kind_before") == "DeriveFeature"
        and p.get("kind_after") not in (None, "DeriveFeature")
        and p.get("definition_after") is None
        and "cannot restore the link" in (p.get("note") or "")
        and fresh() in (p.get("parameters_disappeared") or [])
        and p.get("bodies_left") == [] and p.get("bodies_changed") == []
        and p.get("new_timeline_errors") == []
        and bool(_RECALL.setdefault("de_index", p.get("timeline_index")) is not None)))
    read("design_get", {"include": ["timeline"], "max_results": 100},
         lambda p: _timeline_ok(p) and _measured(
             "the derive's timeline row is no longer a DeriveFeature",
             [(row.get("index"), row.get("type")) for row in p["timeline"]["timeline"]],
             [row.get("type") for row in p["timeline"]["timeline"]
              if row.get("index") == _RECALL.get("de_index")] not in ([], ["DeriveFeature"])
             and all(row.get("type") != "DeriveFeature" for row in p["timeline"]["timeline"])))
    read("model_inspect", _INSPECT, _bodies(2, 1500))
    table_holds("the derived favourite went with the link and the local one stays",
                lambda names: fresh() not in names and derived() in names and dependent(names))
    read("doc_get", {"include": ["default", "xref_tree"]},
         lambda p: p["xref_tree"].get("walk_complete") is True
         and p["xref_tree"].get("reference_link_count") == 0)

    write("doc_activate", lambda c: {"name": c["de_source"]}, _activated(name))
    write("doc_close", lambda c: {"name": c["de_host"], "save_changes": False}, _document_closed,
          owner="de_source")
    write("doc_activate", lambda c: {"name": c["de_home"]}, _activated(), owner="de_source")
    write("doc_close", lambda c: {"name": c["de_source"], "save_changes": False},
          _document_closed, owner="de_home")
    read("doc_get", {}, lambda p: _home_address(p) == _RECALL.get("de_home")
         and not {row.get("document_handle") for row in p["open_documents"]}
         & {_RECALL.get(key) for key in ("de_source", "de_host")})
    return rows


_DERIVE_EDITS = _derive_edit_rows()
