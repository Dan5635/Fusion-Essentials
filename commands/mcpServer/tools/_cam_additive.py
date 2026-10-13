# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Additive (3D printing) setup reads and writes shared by the CAM tools."""

import math

import adsk.cam
import adsk.core
import adsk.fusion

from ._common import safe
from . import _common

MAP_BLURB = ("setting_fits/assign_parts/target_parts (print setting vs machine, an operation's parts), "
             "orientation_rows/choose_orientation, placement_rows, print_setting_row/printer_row, "
             "additive_results - additive setup reads and verified writes.")

# The parameter that holds the parts an additive operation acts on, by the operations that carry it.
PART_TARGETS = ("optimizeOrientationTarget", "supportTarget", "supportTargetModel",
                "interferenceAnalysisTargets")
SUPPORT_TARGETS = ("supportTarget", "supportTargetModel")
SUPPORT_COUNT_NOTE = (
    "generated_result_count reads 0; on a support operation that does not say whether support was "
    "generated. cam_get_status reads whether the operation is valid; has_error and error here read "
    "a failed generation.")
# Two reads of one orientation matrix differ by about 1e-8.
MATRIX_TOL = 1e-6
_ROTATION_CELLS = (0, 1, 2, 4, 5, 6, 8, 9, 10)
_CANDIDATE_VALUES = (("support_volume", "supportVolume"), ("support_area", "supportArea"),
                     ("bounding_box_volume", "boundingBoxVolume"), ("part_height", "partHeight"),
                     ("center_of_gravity_height", "centerOfGravityHeight"),
                     ("ranking_value", "rankingValue"))


def setting_fits(setting, machine):
    """True or False as the print setting says it suits the machine; None when that did not read."""
    return _common.read_flag(lambda: setting.isCompatibleWithMachine(machine))


def unfit_refusal(setting_name, machine_label, fits=False):
    """The refusal for a print setting its machine cannot use."""
    verdict = (f"Print setting '{setting_name}' is not compatible with machine '{machine_label}'"
               if fits is False else
               f"Compatibility of print setting '{setting_name}' with machine '{machine_label}' did not read")
    return (verdict + ", so it was not assigned. cam_get(include=['print_settings'], technology=...) "
            "lists the settings of one technology.")


def _part_path(cam, entity):
    """The design occurrence path of an occurrence or body, with the Manufacture root stripped, or None."""
    occurrence = adsk.fusion.Occurrence.cast(entity)
    if occurrence is None:
        occurrence = safe(lambda: adsk.fusion.BRepBody.cast(entity).assemblyContext)
    path = safe(lambda: occurrence.fullPathName)
    if not isinstance(path, str) or not path:
        return None
    root = safe(lambda: cam.designRootOccurrence.fullPathName)
    return path[len(root) + 1:] if root and path.startswith(root + "+") else path


def part_target(op):
    """((parameter, name), None) for the one parts parameter an operation carries, else (None, reason)."""
    params = safe(lambda: op.parameters)
    hits = [(n, p) for n in PART_TARGETS
            for p in [safe(lambda n=n: params.itemByName(n))] if p is not None]
    if len(hits) != 1:
        return None, (f"Operation '{safe(lambda: op.name)}' (strategy '{safe(lambda: op.strategy)}') "
                      f"carries {len(hits)} part selections of the kinds 'parts' sets; it takes an "
                      "orientation, a support or an interference operation.")
    name, param = hits[0]
    return (param, name), None


def target_parts(cam, param):
    """The design occurrence paths a parts parameter holds, or None when one did not resolve."""
    listed = safe(lambda: list(param.value.value))
    if listed is None:
        return None
    paths = [_part_path(cam, e) for e in listed]
    return None if None in paths else paths


def assign_parts(cam, op, occurrences):
    """({parameter, parts_before, parts}, None) once a fresh read names exactly the parts asked."""
    found, reason = part_target(op)
    if reason:
        return None, reason
    param, name = found
    asked = [safe(lambda o=o: o.fullPathName) for o in occurrences]
    before = target_parts(cam, param)
    try:
        param.value.value = list(occurrences)
    except Exception as e:
        return None, f"The parts were not assigned to '{safe(lambda: op.name)}': {e}."
    fresh = safe(lambda: op.parameters.itemByName(name))
    now = target_parts(cam, fresh) if fresh is not None else None
    if now is None or sorted(now) != sorted(asked):
        return None, (f"'{safe(lambda: op.name)}' does not read the parts asked for after the "
                      f"assignment (asked {asked}, reads {now}). cam_get(include=['additive_results'], "
                      "operation=...) reads it as it is.")
    return {"parameter": name, "parts_before": before, "parts": now}, None


def _cells(matrix):
    cells = safe(lambda: [float(v) for v in matrix.asArray()])
    return cells if cells and len(cells) == 16 and all(math.isfinite(v) for v in cells) else None


def _orientation_set(op):
    """(the operation's one orientation result set, None) or (None, reason); results are told by class."""
    data = safe(lambda: op.generatedDataCollection)
    count = _common.counted(lambda: data.count)
    if count is None:
        return None, f"The generated results of '{safe(lambda: op.name)}' did not read."
    sets = [r for r in (adsk.cam.OptimizedOrientationResults.cast(safe(lambda i=i: data.item(i)))
                        for i in range(count)) if r is not None]
    if len(sets) != 1:
        return None, (f"'{safe(lambda: op.name)}' holds {len(sets)} orientation result sets; generate "
                      "the automatic orientation with cam_generate first.")
    return sets[0], None


def _candidate(result, index=None):
    row = {} if index is None else {"index": index}
    for key, member in _CANDIDATE_VALUES:
        row[key] = _common.measured(lambda member=member: getattr(result, member), 1.0, 6)
    row["transformation"] = _cells(safe(lambda: result.transformation))
    return row


def orientation_rows(op):
    """({count, candidates, current_index}, None): current_index is None until one was chosen."""
    results, reason = _orientation_set(op)
    if reason:
        return None, reason
    count = _common.counted(lambda: results.count)
    if count is None:
        return None, f"The orientation candidates of '{safe(lambda: op.name)}' did not read."
    rows = [_candidate(results.item(i), i) for i in range(count)]
    now = _cells(safe(lambda: results.currentOrientationResult.transformation))
    same = [r["index"] for r in rows if now and r["transformation"]
            and max(abs(a - b) for a, b in zip(now, r["transformation"])) <= MATRIX_TOL]
    return {"count": count, "candidates": rows, "current_index": same[0] if len(same) == 1 else None}, None


def _unit_rotation(cells):
    """The nine rotation cells with each column scaled to unit length, or None."""
    columns = [[cells[4 * row + col] for row in range(3)] for col in range(3)]
    lengths = [math.sqrt(sum(v * v for v in column)) for column in columns]
    if any(length <= 0 for length in lengths):
        return None
    return [cells[i] / lengths[i % 4] for i in _ROTATION_CELLS]


def manufacture_occurrence(cam, design_path):
    """The Manufacture-side occurrence of one design occurrence path, or None unless exactly one."""
    children = safe(lambda: list(cam.designRootOccurrence.childOccurrences)) or []
    hits = [o for o in children if _part_path(cam, o) == design_path]
    return hits[0] if len(hits) == 1 else None


def choose_orientation(cam, op, index):
    """({index, candidate, pose}, None) once the candidate reads current and the part is turned to it."""
    found, reason = part_target(op)
    if reason:
        return None, reason
    parts = target_parts(cam, found[0])
    if not parts or len(parts) != 1:
        return None, (f"'{safe(lambda: op.name)}' reads {parts} as its parts; an orientation is chosen "
                      "for exactly one part. Set it with 'parts' and generate first.")
    results, reason = _orientation_set(op)
    if reason:
        return None, reason
    count = _common.counted(lambda: results.count)
    if count is None:
        return None, (f"The candidate count in the orientation result sets of '{safe(lambda: op.name)}' "
                      "did not read; no candidate was changed. If not generated, run cam_generate; "
                      "then retry cam_get(include=['additive_results']).")
    if count == 0:
        return None, (f"The orientation result sets of '{safe(lambda: op.name)}' contain no candidates. "
                      "Run cam_generate, then read cam_get(include=['additive_results']).")
    if type(index) is not int or not 0 <= index < count:
        return None, (f"'orientation_candidate' is an index from 0 to {count - 1} of the candidates "
                      f"cam_get(include=['additive_results']) lists - got {index!r}.")
    chosen = results.item(index)
    wanted = _cells(safe(lambda: chosen.transformation))
    if wanted is None:
        return None, f"Candidate {index} of '{safe(lambda: op.name)}' did not read its transformation."
    occurrence = manufacture_occurrence(cam, parts[0])
    if occurrence is None:
        return None, (f"Manufacture occurrence '{parts[0]}' did not resolve uniquely among the direct "
                      "parts; no candidate was changed. cam_get(include=['placement'], setup=...) "
                      "reads which part poses are available.")
    try:
        results.currentOrientationResult = chosen
    except Exception as e:
        return None, f"Candidate {index} was not made current on '{safe(lambda: op.name)}': {e}."
    fresh, reason = _orientation_set(op)
    now = None if reason else _cells(safe(lambda: fresh.currentOrientationResult.transformation))
    if now is None or max(abs(a - b) for a, b in zip(now, wanted)) > MATRIX_TOL:
        return None, (f"Candidate {index} does not read as the current orientation of "
                      f"'{safe(lambda: op.name)}' after the assignment.")
    pose = _cells(safe(lambda: occurrence.transform2))
    turned, asked = (_unit_rotation(pose) if pose else None), _unit_rotation(wanted)
    if turned is None or asked is None or max(abs(a - b) for a, b in zip(turned, asked)) > MATRIX_TOL:
        return None, (f"Candidate {index} reads current, but the Manufacture-side pose of '{parts[0]}' "
                      "does not read turned to it. cam_get(include=['placement']) reads the pose.")
    return {"index": index, "candidate": _candidate(chosen), "part": parts[0], "pose": pose}, None


def placement_rows(cam, setup, inv_k):
    """([row per model of the setup: its Manufacture-side pose and box], None) or (None, reason)."""
    models = safe(lambda: list(setup.models))
    if models is None:
        return None, f"The models of setup '{safe(lambda: setup.name)}' did not read."
    rows = []
    for model in models:
        path = _part_path(cam, model)
        occurrence = manufacture_occurrence(cam, path) if path else None
        box = safe(lambda: occurrence.boundingBox)
        low = safe(lambda: [round(c * inv_k, 6) for c in box.minPoint.asArray()])
        high = safe(lambda: [round(c * inv_k, 6) for c in box.maxPoint.asArray()])
        pose = _cells(safe(lambda: occurrence.transform2))
        if pose is not None:
            pose = [round(v * (inv_k if i in (3, 7, 11) else 1.0), 9) for i, v in enumerate(pose)]
        rows.append({"part": path, "pose": pose, "min_point": low, "max_point": high,
                     "read": occurrence is not None and pose is not None})
    return rows, None


def _table(params, limit):
    count = _common.counted(lambda: params.count)
    if count is None:
        return None, None
    return [{"name": safe(lambda i=i: params.item(i).name),
             "expression": safe(lambda i=i: params.item(i).expression)} for i in range(min(count, limit))], count


def print_setting_row(setup, limit=40):
    """The setup's print setting: identity, its items and its general table."""
    setting = safe(lambda: setup.printSetting)
    if setting is None:
        return None
    count = _common.counted(lambda: setting.count)
    general, general_count = _table(
        safe(lambda: setting.parameters(adsk.cam.PrintSettingItemTypes.GENERAL)), limit)
    return {"name": safe(lambda: setting.name), "technology": safe(lambda: setting.technology),
            "description": safe(lambda: setting.description),
            "compatible_with_machine": setting_fits(setting, safe(lambda: setup.machine)),
            "items": None if count is None else [safe(lambda i=i: setting.item(i).name)
                                                 for i in range(min(count, limit))],
            "item_count": count, "items_truncated": count > limit if count is not None else None,
            "default_item": safe(lambda: setting.getDefaultPrintSettingItem().name),
            "general": general, "general_count": general_count,
            "general_truncated": general_count > limit if general_count is not None else None}


def printer_row(setup, inv_k):
    """The setup's machine as a printer: platform, FFF limits and extruders, lengths in caller units."""
    machine = safe(lambda: setup.machine)
    if machine is None:
        return None
    elements = safe(lambda: machine.elements)
    count = _common.counted(lambda: elements.count)
    row = {"vendor": safe(lambda: machine.vendor), "model": safe(lambda: machine.model),
           "platform": None, "limits": None, "extruders": [] if count is not None else None,
           "element_count": count}
    if count is None:
        return row

    def point(p):
        return [round(c * inv_k, 6) for c in (p.x, p.y, p.z)]
    for i in range(count):
        element = safe(lambda i=i: elements.item(i))
        platform = adsk.cam.AdditivePlatformMachineElement.cast(element)
        limits = adsk.cam.AdditiveFFFLimitsMachineElement.cast(element)
        extruder = adsk.cam.ExtruderMachineElement.cast(element)
        if platform is not None:
            row["platform"] = {"size": safe(lambda: point(platform.size)),
                               "origin": safe(lambda: point(platform.origin)),
                               "clearance": _common.measured(lambda: platform.clearance, inv_k, 6)}
        elif limits is not None:
            row["limits"] = {"max_bed_temperature_c": safe(lambda: limits.maximumBedTemperature),
                             "max_xy_speed_per_s": _common.measured(lambda: limits.maximumXYSpeed, inv_k, 6),
                             "max_z_speed_per_s": _common.measured(lambda: limits.maximumZSpeed, inv_k, 6)}
        elif extruder is not None:
            row["extruders"].append({
                "name": safe(lambda: extruder.name),
                "nozzle_diameter": _common.measured(lambda: extruder.nozzleDiameter, inv_k, 6),
                "filament_diameter": _common.measured(lambda: extruder.filamentDiameter, inv_k, 6),
                "max_temperature_c": safe(lambda: extruder.temperature)})
    return row


def additive_results(cam, op):
    """What one additive operation holds after generation: its parts, state and typed results."""
    found, _reason = part_target(op)
    out = {"operation": safe(lambda: op.name), "strategy": safe(lambda: op.strategy),
           "parts": target_parts(cam, found[0]) if found else None,
           "has_error": _common.read_flag(lambda: op.hasError), "error": safe(lambda: op.error) or None,
           "has_warning": _common.read_flag(lambda: op.hasWarning),
           "warning": safe(lambda: op.warning) or None}
    data = safe(lambda: op.generatedDataCollection)
    count = _common.counted(lambda: data.count)
    out["generated_result_count"] = count
    if count == 0 and found and found[1] in SUPPORT_TARGETS:
        out["note"] = SUPPORT_COUNT_NOTE
    for i in range(count or 0):
        # an item is told by its class: asking the collection by type hands back whatever it holds
        clash = adsk.cam.AdditiveInterferenceAnalysisResult.cast(safe(lambda i=i: data.item(i)))
        if clash is not None:
            out["interfering_parts"] = safe(lambda: sorted(
                _part_path(cam, o) or "?" for o in clash.interferingOccurrences))
    rows, reason = orientation_rows(op)
    if not reason:
        out["orientation"] = rows
    return out
