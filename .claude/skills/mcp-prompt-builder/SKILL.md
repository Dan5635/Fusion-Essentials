---
name: mcp-prompt-builder
description: >-
  Author or revise a Fusion CAD/CAM product-design or recorded-showcase brief with
  reference-based quality criteria, staged reviews, and explicit evidence requirements.
  Use for preparing an executor's task, not ordinary modeling, server testing, or grading
  a running evaluation against newly added requirements.
---

# Author a Fusion design brief

Make product quality and function determine progress. Healthy features, tool coverage,
operation counts and drawing-page counts do not establish a good design.

Draft the brief offline. Preserve the user's product, scope, tool permissions and priorities.
Do not acquire the Fusion session, launch an evaluation or change a running task merely to
prepare its prompt. Keep requirements and grading criteria identical; proposed additions
must be visible before a run, not introduced afterward by its reviewer.

## Shape the brief

Use a compact product description, a small reference board and an acceptance table. Keep
supporting research separate from executor instructions. Include only criteria relevant to
the product; do not turn every previous usecase failure into a universal requirement.

1. **Product and references.** State the intended user, function, manufacturing process and
   expected finish. Identify hard requirements, styling targets and later deliverables.
   Supply references or direct the executor to research them. Distinguish published,
   measured, estimated and chosen dimensions; perspective images are not exact dimensions.
2. **Decisive acceptance criteria.** For each important form or interface, specify the desired
   outcome, which geometry it applies to, the view or measurement that judges it, and what
   must happen if it fails. Use requirement-based thresholds. For visual quality, identify
   reference views and concrete defects to inspect rather than inventing a numeric score.
3. **Stages.** Order work by dependencies: product form and interfaces, assembly/mechanisms,
   manufacturing states and CAM, then useful drawings and exports. Place accessories where
   the user prioritized them. Reserve effort for revision and verification before expanding
   detail. Choose appropriate constructions; avoid tool-family quotas.
4. **Review and correction.** At a stage boundary, compare actual geometry with its criteria
   using readable images and independent measurements. Revise defects before advancing to
   dependent work. If a capability blocks a required result, save the work and state the
   failed criterion and concrete blocker. Independent work may continue, but downstream
   deliverables do not convert that failure into completion.

## Instructions to carry into the executor's brief

- Keep at most one Fusion request outstanding, including reads. Inspect its reply before
  the next request. Follow the assigned session ownership and document guards.
- After a refused edit, re-read the target property the edit could change and relevant
  history or ownership before trying its remedy. Name that property in a bounded test:
  unchanged whole-design bounds or object counts can conceal a local geometry change.
- Build intended changeability with useful parameters and stable references. When the task
  requires parametric robustness, specify a representative change-and-restore check of
  dependent geometry and health. Named parameters alone are not proof. Otherwise offer
  this as a diagnostic, not an undisclosed acceptance requirement.
- For mechanisms, check physical interfaces and intermediate motion as well as endpoints.
  Scalar joint values or motion links alone do not prove contact, restraint or transmission.
  Distinguish rigid poses from verified elasticity, holding force or load capacity.
- For CAM, distinguish generated paths, stock removal, cutter/shank/holder clearance,
  fixture states, posted output and machine execution. Require only evidence available
  within the authorized task; keep unsupported manufacturing claims explicitly unverified.
- Before meaningful work blocks, explain the design purpose briefly and frame the relevant
  input at a readable scale. Use orthographic views for layout, oblique views and useful
  contrast for surface form, sections for internal interfaces, and motion views for
  mechanisms. Reframe after configuration changes. Inspect captured images; blank, distant
  or obscured views are not evidence. Show stock, fixtures and complete tools together when
  reviewing machining access.
- Save at completed stages. Deliver useful native files, drawings and requested exports,
  with representative evidence and separate conclusions on appearance, function,
  manufacturability and remaining uncertainty. Report consequential blockers without a
  transcript of routine successes.

## Review the drafted prompt

Check that each mandatory criterion is visible to the executor, has a feasible observation,
and fits the allotted work budget. Separate core requirements from deferrable detail.
Do not silently expand scope with extra products, tools, scripts or evaluations. Keep the
exact executed brief and later steering associated with the run. Evaluate older runs
against their own instructions; edited video quality is not a CAD quality measurement.

No new evaluator software or automatic review loop is required.
