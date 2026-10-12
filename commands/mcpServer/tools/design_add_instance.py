# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: place another INSTANCE of a component that already exists in this design -
the counterpart to model_create_component, which mints an empty one. WRITES.

Fusion numbers a new instance off a GLOBAL per-component counter ('BasePlate:2' - measured), so the
landed name and path are read back off the assembly tree instead of being predicted.
"""

import math

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import component_contains, error, occurrence_paths, ok, safe, scale
from . import _common
from . import _inputs
from . import _outputs
from ._doc_common import component_solids as _solids

# collapse_ambiguous_occurrences is on because the target here IS the component: a name matching
# several of its instances is not an ambiguity to refuse, since instancing a component that already
# has instances is this tool's job.
_COMPONENT = _inputs.TargetRef("component", allow=("occurrence", "component"), required=True,
        collapse_ambiguous_occurrences=True)
_INTO_COMPONENT = _inputs.OccurrenceRef("into_component")

RETURNS = [
    _outputs.ReturnsName("full_path", of="new instance",
                         consumers=["joint_create", "assembly_move", "design_move_occurrence"]),
]

# How far the landed local matrix may sit from the requested one: translation cells in cm, axis cells.
_ORIGIN_TOL_CM = 1e-6
_AXIS_TOL = 1e-5
_ORIGIN_CELLS = (3, 7, 11)
_AXIS_CELLS = {"x": (0, 4, 8), "y": (1, 5, 9), "z": (2, 6, 10)}


def _cells(matrix):
    """A Matrix3D's 16 row-major cells as floats, or None when they did not read."""
    vals = safe(lambda: [float(v) for v in matrix.asArray()])
    return vals if isinstance(vals, list) and len(vals) == 16 else None


def _off_request(want, got):
    """True when the landed cells leave the requested ones beyond the origin or axis tolerance."""
    return (any(abs(got[i] - want[i]) > _ORIGIN_TOL_CM for i in _ORIGIN_CELLS)
            or any(abs(got[i] - want[i]) > _AXIS_TOL for c in _AXIS_CELLS.values() for i in c))


_IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _mul(a, b):
    """The row-major product a.b of two 16-cell matrices."""
    return [sum(a[4 * r + i] * b[4 * i + c] for i in range(4)) for r in range(4) for c in range(4)]


def _rigid_inverse(m):
    """The inverse of a rigid 16-cell matrix: its rotation transposed, its origin carried back."""
    rot = [[m[4 * c + r] for c in range(3)] for r in range(3)]
    back = [-sum(rot[r][i] * m[4 * i + 3] for i in range(3)) for r in range(3)]
    return [*rot[0], back[0], *rot[1], back[1], *rot[2], back[2], 0.0, 0.0, 0.0, 1.0]


def _world_at_path(design, comp, path):
    """World cells of one uniquely addressed component placement, or None."""
    if comp is None or not isinstance(path, str) or not path:
        return None
    occs = safe(lambda: design.rootComponent.allOccurrencesByComponent(comp))
    count = _common.counted(lambda: occs.count)
    if count is None or count < 0:
        return None
    matches = []
    for index in range(count):
        occ = safe(lambda: occs.item(index))
        found = safe(lambda: occ.fullPathName)
        if not isinstance(found, str) or not found:
            return None
        if found == path:
            matches.append(occ)
    return _cells(safe(lambda: matches[0].transform2)) if len(matches) == 1 else None


def _landed_local(design, comp, path, host, host_path):
    """Current landed local cells derived from exact placed and host world poses, or None."""
    world = _world_at_path(design, comp, path)
    host_world = _world_at_path(design, host, host_path) if host is not None else _IDENTITY
    if world is None or host_world is None:
        return None
    return _mul(_rigid_inverse(host_world), world)


def _first_world(design, comp):
    """World cells of the occurrence of `comp` the assembly walk lists first, or None when unread."""
    occs = safe(lambda: design.rootComponent.allOccurrencesByComponent(comp))
    if occs is None or not safe(lambda: occs.count):
        return None
    return _cells(safe(lambda: occs.item(0).transform2))


def _cells_to_pass(design, comp, host, want):
    """The cells addExistingComponent must be given to land at `want`; None when a pose is unread."""
    # Direct design lands an instance at inv(H).M.W, parametric at inv(H).W.H.inv(W).M: H and W are
    # the world poses of the walk-first occurrence of the host and of the component, M the matrix
    # passed. A parametric identity M lands at inv(H).W, so a request needing one still misses.
    world = _first_world(design, comp)
    host_world = _first_world(design, host) if host is not None else _IDENTITY
    direct = safe(lambda: design.designType == adsk.fusion.DesignTypes.DirectDesignType)
    if world is None or host_world is None or direct is None:
        return None
    if direct:
        return _mul(_mul(host_world, want), _rigid_inverse(world))
    shift = _mul(_mul(_rigid_inverse(host_world), world), _mul(host_world, _rigid_inverse(world)))
    return _mul(_rigid_inverse(shift), want)


def _frame(cells, k):
    """(local origin in 'units', {axis: unit vector}) off a matrix's cells."""
    origin = {a: round(cells[i] / k, 6) for a, i in zip("xyz", _ORIGIN_CELLS)}
    return origin, {a: [round(cells[i], 6) for i in c] for a, c in _AXIS_CELLS.items()}


def _host_prefixes(paths, instance_name):
    """The distinct HOST-INSTANCE paths among `paths` - each path's portion above the new instance's
    own segment ('' = the root). This is how many hosts received the instance; the leftover paths do
    NOT count, because every host instance also contributes the new instance's own children."""
    out = set()
    for p in paths:
        parts = p.split("+")
        if instance_name in parts:
            out.add("+".join(parts[:parts.index(instance_name)]))
    return out


def _is_external(design, entity, kind, comp):
    """True / False / None: does the source component come from another file?"""
    if kind == "occurrence":
        return _common.read_flag(lambda: entity.isReferencedComponent)
    occs = safe(lambda: design.rootComponent.allOccurrencesByComponent(comp))
    if occs is None or not safe(lambda: occs.count):
        return None
    return _common.read_flag(lambda: occs.item(0).isReferencedComponent)


def _copy_fault(design, comp, comp_name, occ, components_before, source_before):
    """The error for a 'copy' that is not an independent copy of an unchanged source, or ''."""
    made = safe(lambda: occ.component)
    same = _common.same_component(made, comp) if made is not None else None
    if same is not False:
        return (f"No independent copy of '{comp_name}' was made: the new occurrence "
                + ("is another instance of that same component." if same else
                   "did not read its component, so it cannot be told from a shared instance."))
    components_after = safe(lambda: design.allComponents.count)
    if components_after != components_before + 1:
        return (f"The copy of '{comp_name}' took the design from {components_before} to "
                f"{components_after} components, not one more.")
    copied, source_after = _solids(made), _solids(comp)
    if source_after != source_before:
        return (f"Copying '{comp_name}' changed the source: its bodies read "
                f"{source_after[0]} / {source_after[1]} cm3 against {source_before[0]} / "
                f"{source_before[1]} before.")
    if copied[0] != source_before[0]:
        return (f"The copy of '{comp_name}' holds {copied[0]} body(ies) against the source's "
                f"{source_before[0]}.")
    if copied[1] is None or (
            abs(copied[1] - source_before[1]) > 1e-9 * max(1.0, abs(source_before[1]))):
        return (f"The copy of '{comp_name}' reads a volume of {copied[1]} cm3 against the "
                f"source's {source_before[1]}.")
    return ""


def handler(component: str = "", into_component: str = "", x: float = 0.0, y: float = 0.0,
            z: float = 0.0, units: str = "mm", rotate_deg: float = 0.0,
            rotate_axis: str = "z", independent: bool = False) -> dict:
    """See TOOL_DESCRIPTION."""
    k = scale(units)
    if k is None:
        return error(f"Unknown units '{units}'. Use mm, cm, or in.")
    design = _common.design()
    if not design:
        return error("No active design. Open or create a document first (see doc_new).")

    resolved, cerr = _COMPONENT.resolve(component)
    if cerr:
        return cerr if isinstance(cerr, dict) else error(cerr)
    entity, kind = resolved
    comp = safe(lambda: entity.component) if kind == "occurrence" else entity
    if comp is None:
        return error(f"Could not reach the component behind '{component}' to instance it.")
    comp_name = safe(lambda: comp.name) or component

    host_path, nested_host = "", None
    if (into_component or "").strip():
        into_occ, ierr = _INTO_COMPONENT.resolve(into_component)
        if ierr:
            return error(ierr)
        host = safe(lambda: into_occ.component)
        if host is None:
            return error(f"Occurrence '{into_component}' has no component to instance into.")
        host_path, nested_host = safe(lambda: into_occ.fullPathName) or "", host
        host_label = f"component '{safe(lambda: host.name)}' ({host_path})"
    else:
        host = safe(lambda: design.rootComponent)
        if host is None:
            return error("Could not reach the root component to instance into.")
        host_label = "the root component"

    # A component cannot hold an instance of itself (nor of anything it already sits inside): the
    # platform refuses it too, with '3 : add operation failed'. This guard is the named error.
    cycle = component_contains(comp, host)
    if cycle is True:
        return error(f"Refusing to instance '{comp_name}' into {host_label}: that target is "
                     f"'{comp_name}' itself or sits inside it, so the component would contain an "
                     "instance of itself. Pick a target outside it (omit 'into_component' for root).")
    if cycle is None:
        # The walk answers None for several distinct reads, so the wire says only what is common to
        # them: no verdict was reached.
        return error(f"Refusing to instance '{comp_name}' into {host_label}: whether that target "
                     f"already sits inside '{comp_name}' could not be determined - the subtree could "
                     "not be searched to a verdict, so the instance could make the component contain "
                     "itself. Check for unresolved external references with assembly_get, then "
                     "retry.")

    if independent:
        external = _is_external(design, entity, kind, comp)
        if external is not False:
            return error(
                f"independent=true copies a LOCAL component; '{comp_name}' "
                + ("is an external reference, and a copy of one is only another instance of the "
                   "same file. Break its link first (doc_update_xref action='break_link'), then "
                   "copy the local component that results." if external else
                   "did not read whether it is an external reference, so no copy was made."))
    components_before = safe(lambda: design.allComponents.count)
    source_before = _solids(comp)
    if independent and (None in source_before or not isinstance(components_before, int)
                        or isinstance(components_before, bool)):
        return error(f"The bodies of '{comp_name}' or the design's component count did not read, "
                     "so a copy could not be checked against its source; no copy was made.")

    matrix = adsk.core.Matrix3D.create()
    if rotate_deg:
        axis_vec = _inputs._AXIS_VECS.get((rotate_axis or "z").strip().lower())
        if not axis_vec:
            return error(f"Unknown rotate_axis '{rotate_axis}'. Use x, y, or z.")
        # Rotate about the world origin; the translation set below places the instance. (Rotating
        # about the placement point would only bake a pivot correction into the translation column
        # that the next line overwrites anyway - net result is identical, so keep it explicit.)
        if not matrix.setToRotation(math.radians(float(rotate_deg)),
                                    adsk.core.Vector3D.create(*axis_vec),
                                    adsk.core.Point3D.create(0, 0, 0)):
            return error(f"Could not build the placement rotation ({rotate_deg} deg about "
                         f"'{rotate_axis}') - the instance was not created.")
    if x or y or z:
        matrix.translation = adsk.core.Vector3D.create(float(x) * k, float(y) * k, float(z) * k)

    before = occurrence_paths(design)
    occurrences = safe(lambda: host.occurrences)
    if occurrences is None:
        return error(f"Could not access the occurrences of {host_label} to instance into.")
    want = _cells(matrix)
    # The shared-instance landing rule was measured on addExistingComponent only; a copy is given
    # the requested matrix as it is and judged on where it reads afterwards.
    passed = matrix
    cells = want and not independent and _cells_to_pass(design, comp, nested_host, want)
    if cells and _off_request(want, cells):
        passed = adsk.core.Matrix3D.create()
        if not passed.setWithArray(cells):
            passed = matrix
    try:
        # The MUTATION - not safe-wrapped, so a refusal is reported instead of swallowed.
        occ = (occurrences.addNewComponentCopy(comp, passed) if independent
               else occurrences.addExistingComponent(comp, passed))
    except Exception as e:
        return error(f"Could not instance '{comp_name}' into {host_label}: {e}")
    if not occ:
        return error(f"addExistingComponent returned nothing - no instance of '{comp_name}' was "
                     "created.")
    if independent:
        fault = _copy_fault(design, comp, comp_name, occ, components_before, source_before)
        if fault:
            return error(fault + f" The occurrence '{safe(lambda: occ.name)}' it returned is in "
                         "the design; read it with design_get(include=['tree']).")
    # read_flag: the ONE unreadable-flag read - None is unknown, so only a real False refuses.
    if _common.read_flag(lambda: occ.isValid) is False:
        return error(f"addExistingComponent returned an occurrence for '{comp_name}' but it reads "
                     "isValid=false - the instance did not land.")

    # Read the instance back off the assembly tree - the landed name is a READ, never a prediction.
    after = occurrence_paths(design)
    # An UNREADABLE walk yields the SAME empty set an empty assembly would, and the host occurrence
    # this instanced into proves the assembly is not empty - so an empty census is a failed read.
    # Naming "no new instance appeared" over it states a verdict the walk never delivered.
    if not after:
        return error(f"addExistingComponent returned an occurrence for '{comp_name}', but the "
                     "assembly census that confirms it could not be read - the instance may or may "
                     "not have landed. Re-read with design_get(include=['tree']).")
    new_paths = sorted(p for p in (after - before) if p)
    if not new_paths:
        return error(f"The call reported an occurrence for '{comp_name}' but no new instance "
                     "appeared in the assembly tree. Re-read with design_get(include=['tree']).")
    # The instance the CALLER asked for sits under the host occurrence it named; the other new paths
    # are the same instance under the host's OTHER instances ('Frame:1+Bolt:2' AND 'Frame:2+Bolt:2'
    # from one call), so the requested one is the primary.
    under_host = [p for p in new_paths if p.startswith(host_path + "+")] if host_path else new_paths
    full_path = (under_host or new_paths)[0]
    landed = full_path.split("+")[-1] or safe(lambda: occ.name)

    # The landed local matrix is read back and judged against the request, never the passed matrix.
    got = _landed_local(design, safe(lambda: occ.component), full_path, nested_host, host_path)
    frame = _frame(got, k) if got is not None else None
    placed = bool(x or y or z or rotate_deg)
    off = want is not None and frame is not None and _off_request(want, got)
    if off and placed:
        (ox, oy, oz), axes = frame[0].values(), frame[1]
        offset = math.dist([got[i] for i in _ORIGIN_CELLS], [want[i] for i in _ORIGIN_CELLS]) / k
        return error(
            f"Instanced '{comp_name}' as '{landed}' at '{full_path}' (kept), but not at the "
            f"requested placement: its local origin in {host_label} reads ({ox}, {oy}, {oz}) "
            f"{units}, {round(offset, 6)} {units} from the requested one, local axes x {axes['x']} "
            f"y {axes['y']} z {axes['z']}. Its transform was not reset to the request. Move it "
            "with assembly_move, then read it with assembly_get.")

    # Host instances are counted by their distinct PREFIXES, never by counting leftover paths: each
    # host instance also contributes the new instance's children, which are not host instances.
    children = [p for p in new_paths if p.startswith(full_path + "+")]
    host_instances = _host_prefixes(new_paths, landed) or {host_path}

    note = (f"Instanced '{comp_name}' - it LANDED as '{landed}' at '{full_path}'. Fusion numbers a "
            "new instance from a per-component counter across the whole design, so use the landed "
            "name/full_path, not a predicted one. The instance SHARES the component's geometry - "
            "editing either shows in both. Position it with assembly_move / joint_create; re-parent "
            "it with design_move_occurrence.")
    copy_name = safe(lambda: occ.component.name) if independent else None
    if independent:
        note = (f"Copied '{comp_name}' as the NEW component '{copy_name}' - it LANDED as "
                f"'{landed}' at '{full_path}', with its own geometry. Joints on the source were "
                "not copied. Position it with assembly_move / joint_create.")
    if children:
        note += (f" '{comp_name}' holds sub-components, so {len(children)} child path(s) came with "
                 f"it - a child KEEPS its own number ('{children[0].split('+')[-1]}').")
    if len(host_instances) > 1:
        note += (f" The host has {len(host_instances)} instances, so the one call landed the instance "
                 "under each of them (see 'paths').")
    # An x/y placement sets no pending-position flag, so assembly_capture_position refuses it with
    # "Nothing to capture", and in a design holding captured position markers a later joint creation
    # reverts the instance to the origin.
    if x or y or z or rotate_deg:
        note += (" The placement cannot be captured - it sets no pending-position flag, so "
                 "assembly_capture_position refuses it. In a design that HOLDS captured position "
                 "markers, a later joint creation can revert this instance to the ORIGIN. Read the "
                 "position back with model_inspect after the next joint creation, or place the "
                 "instance BY that joint instead of by x/y/z.")
    if off:
        ox, oy, oz = frame[0].values()
        note += f" No placement was requested; it reads at ({ox}, {oy}, {oz}) {units} in {host_label}."
    if want is None or frame is None:
        note += (" The landed placement was not compared with the request: "
                 + ("its local frame could not be read." if frame is None
                    else "the requested matrix did not read."))

    out = {
        "created": True,
        "component": comp_name,
        "occurrence": landed,
        "full_path": full_path,
        "paths": new_paths,
        "into_component": host_label,
        "rotate_deg": float(rotate_deg or 0.0),
        "rotate_axis": (rotate_axis or "z").lower() if rotate_deg else None,
        "units": units,
        "note": note,
    }
    if frame is not None:
        # Read back off the instance, local to its host.
        out["position"], out["axes"] = frame
    if independent:
        out["independent"] = True
        out["new_component"] = copy_name
    return ok(out)


TOOL_DESCRIPTION = (
"Place another INSTANCE of a component already in this design - it SHARES the original's "
"geometry unless 'independent'; placement coords in 'units', angles in degrees.\n"
+ _outputs.produces_block(RETURNS)
)

tool = (
    Tool.create_simple(name="design_add_instance", description=TOOL_DESCRIPTION)
    .add_input_property(*_COMPONENT.as_property())
    .add_input_property(*_INTO_COMPONENT.as_property())
    .add_input_property("x", {"type": "number"})
    .add_input_property("y", {"type": "number"})
    .add_input_property("z", {"type": "number"})
    .add_input_property(*_inputs.UNITS.as_property())
    .add_input_property("rotate_deg", {"type": "number",
            "description": "About 'rotate_axis'."})
    .add_input_property(*_inputs.frame_axis("rotate_axis", default="z",
            description="World axis.").as_property())
    .add_input_property("independent", {"type": "boolean", "description": (
        "true = a NEW local component; external references refused.")})
    .strict_schema()
)
item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(
        kind="inline", rung="value",
        evidence_test="tests/unit/test_design_add_instance.py::TestHonesty"
                      "::test_an_occurrence_returned_with_an_unchanged_tree_is_an_error"))


def register_tool():
    register(item)
