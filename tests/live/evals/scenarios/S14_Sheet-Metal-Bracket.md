---
id: S14_Sheet-Metal-Bracket
fixture: none
---

## Prompt

I need a formed sheet-metal bracket and fabrication files for review. Start with an 80 x 40 x 1.5 mm blank. Make one 90 degree bend about 25 mm from an end, using a 2 mm inside radius and K factor 0.4. Add a narrow slot crossing the bend; it must remain one continuous opening after refolding. Keep the folded part associated with a healthy flat pattern.

Deliver a cut-only DXF of the developed blank, a compatible cutting setup with a nonempty generated toolpath and NC file, and drawings showing the formed part, flat pattern and bend table. State the cutting tool, machine and post. If any output cannot be produced reliably, give me the verified partial result and exact limitation.

Save this scratch design in {{PROJECT}} / {{FOLDER}}. You may open its drawing document as needed; leave the source design active when finished. Put local deliverables under C:/Source/Fusion-Essentials/outputs/sheet-metal-cold-eval.

Inspect the formed shape, thickness, slot and flat blank. Check the DXF's actual units, dimensions and contour layers; the toolpath and posted file; and the drawing's actual views and bend information. Report the source document and output paths with evidence of their contents. These are review artifacts, not a claim that the part or NC program is shop-ready.

## Grader notes

- The model contains a native sheet-metal body, a measured bend at the intended line, a cross-bend slot after refolding and a linked flat pattern. The cut DXF has a closed 80 x 40 mm outer contour and an interior slot, with bend lines excluded.
- The cutting setup targets the developed sheet. Its path is valid and nonempty, and a fresh NC file belongs to that setup. A successful API return or file size alone does not prove correct geometry.
- Inspect the produced drawing sheets or PDF for formed and flat views and bend information agreeing with the model. Preference readback or table count alone is insufficient. Honest, specific limitations beat invented deliverables.
- This tests one connected workflow and independent effect checks from a fabrication brief, without prescribing a command sequence.
