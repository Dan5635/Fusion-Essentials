---
name: parametric-cad-design
description: >-
  Use when designing or modelling in Fusion through the fusion-essentials tools - building a
  part, a surfaced product, an assembly, or a machining job, not running a fixed procedure.
  Rules are conditional strategies unless marked as a safety invariant; recipes demonstrate one
  construction with stated prerequisites, and their exemplars are examples, not requirements.
---

# Designing in Fusion

Choose constructions by intended behavior and verify their effects. Recipes are worked examples: follow their dependencies, allowing companion reads, intermediate calls and justified alternatives.

## Kernel

**declare-acceptance-and-interfaces** - Write what the design must satisfy and each interface as a checkable number - seating faces, aligned axes, clearance, wall thickness when you take on a brief; not for a throwaway probe. Prove: `workspace_orient`: the active document, its units and what is already in it.

**sequence-is-the-design** - Treat a sample sequence as one option; choose references and feature order for the interfaces and edits they must preserve when choosing a construction; not for a one-feature part with no downstream dependency. Prove: `design_get`: the relevant feature expressions and health after a representative intended edit; `param_get`: with trace=true, parameter-expression dependents; geometric references need separate checks.

**encode-intended-changeability** - Share a dimension when values must track; keep independent decisions independent; name important drivers so later edits express intent when a value carries a decision; not for a fixed reference whose source and role are stated. Prove: `sketch_get`: the intended expressions and their evaluated dimensions.

**build-and-observe-in-milestones** - Treat a successful call or healthy feature as partial evidence; check the actual effect against intent with relevant measurements and a useful view when a milestone lands; not for an effect already independently checked at this milestone. Prove: `model_inspect`: bounds and volume of the changed body and relevant neighbors.

**compare-the-artifact-with-acceptance** - Compare the result with requirements and declared choices; distinguish what was created, computed, measured and tested from what remains unverified when the design looks finished; not for a disposable probe that makes no product claim. Prove: `view_screenshot`: a view supporting the measured interfaces and intended form.

## Playbooks

A playbook `<id>` is the file `playbooks/<id>.md`, or `sys_get_guidance(section="<id>")`.

- `plan` - before the first component exists - naming, variants, what is bought
- `sketch` - any profile that must survive a size change or drive a feature
- `model` - turning sketches into a part - order, carving, patterns, threads, sheet metal, frozen bodies
- `surface` - a shell, skin or product form that is not required to be manifold
- `assemble` - more than one component - how they are referenced, joined and moved
- `validate` - the geometry exists and must be proved against the brief
- `finish` - handing the work on
- `manufacture` - a machining job - setups, strategy choice, what a toolpath must prove

## Recipes

A recipe `<id>` is `sys_get_guidance(recipe="<id>")` - one worked construction: its prerequisites, steps each with a read-back, a bar for done. Its prefix names the playbook it belongs to.

- `sketch-anchored-profile` - a planar profile whose halves must track; choose its component, sketch plane and intended symmetry first
- `sketch-link-between-bores` - a web joining bosses; first create a sketch with resolved pivot references and decide which dimensions must track
- `sketch-organic-outline` - a free outline needing controlled end tangency; first create its sketch and decide which parts of the shape must be editable
- `model-moulded-part` - a shell whose outer envelope is conveniently built before its wall; prepare the dimensioned sketches and choose a pull direction
- `model-frozen-body-with-interfaces` - an imported part whose supplied form should remain a reference; choose its component, placement and permitted interface changes first
- `model-parametric-family` - variants share a useful parametric definition and configurations are available; prepare the component and profile sketch first
- `surface-swept-bottle` - a changing-section container; prepare compatible body/neck profiles, rails, a crown profile and any required closure surfaces
- `surface-skin-into-parts` - separate part documents must follow one master skin; prepare the master's sections/rails and each part's closing boundaries
- `assemble-part-modelled-in-place` - a part is designed in its intended assembled pose; prepare its component/sketch and identify the actual members and required freedoms
- `assemble-screw-motion` - distinct rotating and translating members need an ideal pitch relationship; this does not model one cap both turning and advancing
- `manufacture-choose-a-strategy` - a prepared setup and tool library need a cutting operation for a known feature; choose from available strategies
- `manufacture-prove-a-toolpath` - a cutting operation expected to remove stock needs review before a demonstration post; machine release requires its own process checks
- `manufacture-radial-hole-across-the-axis` - a known hole crosses a turned axis; decide through/blind intent, entry side, access and required depth before selecting a setup
