# papercraft-nester

A separate optimizer for the SVG and manifest produced by [`lowpoly-pdf-to-svg`](https://github.com/tungufoss/lowpoly-pdf-to-svg). It does not embed that tool: run both from a models repository that holds the two as submodules (for example `tools/lowpoly-pdf-to-svg` and `tools/papercraft-nester`) next to `data/<model>/`. It nests complete labeled pieces onto finite cardstock inventory and exports one project-wide SVG master with an Inkscape page per physical sheet.

The [project site](https://tungufoss.github.io/papercraft-nester/) has a step-by-step [guide](https://tungufoss.github.io/papercraft-nester/guide.html) and [methods](https://tungufoss.github.io/papercraft-nester/methods.html), using the same Quarto theme as `lowpoly-pdf-to-svg`.

## First benchmark

The initial Bowser benchmark uses Letter sheets and the material assignments in `data/bowser/bowser.yaml` of the models repository. It reads only editable piece groups from `bowser.svg`; hidden/source review layers are ignored. Each piece retains its cut outline, mountain folds, valley folds, labels, ID, and cardstock material together. The source PDF and generated review SVG are intentionally local inputs and are not part of any public repository. Place the PDF at the manifest's configured path and run the converter's `make` target before nesting.

The sample inventory is in `config/bowser-letter.json`. Its quantities (7 red, 3 green, 10 yellow, 1 black) match the source PDF's current material page counts; update quantities and sheet dimensions to represent actual stock. The benchmark default minimum gap is 0.2 mm, matching the tight clearances in the source layout (minimum observed source gap is about 0.29 mm); change this for the stock and blade you use. Each inventory row may have a different sheet size, so stock sizes can be mixed within a color.

## Run

From the repository root (paths below assume it sits in `tools/` of the models repository), install with `python -m pip install -e .`, then:

```text
papercraft-nester nest --svg ../../data/bowser/bowser.svg --manifest ../../data/bowser/bowser.yaml --inventory config/bowser-letter.json --output output/bowser-letter-master.svg
``

Alternatively, run `python -m papercraft_nester.cli nest ...` with `PYTHONPATH=src`.

The optimizer reports source sheet counts, packed sheet counts, utilization, and estimated reposition distance. The first version uses deterministic polygon placement heuristics; it is not a proof of globally optimal nesting. It supports rigid rotation with configurable angular search resolution and keeps complete piece outlines apart in its initial mode.

## Cut path per sheet

`papercraft-nester cutpath` orders the tool paths on each sheet of the converter's `<model>-export.svg`, leaving every piece where it is (no nesting). Each sheet (source page) is solved on its own, in four passes: **Cut** (a piece is always cut in one go; an edge within `--share-tol` of one a neighbour already cut is skipped), **Fold valley** and **Fold mountain** (separate passes, each fold line in either direction) and **Draw** (the short glue labels as single-stroke pen paths). It reads only the export SVG, so it works whatever state the glue pairs or 3D fold are in.

```text
papercraft-nester cutpath --svg ../../data/bowser/bowser-export.svg --output ../../data/bowser/bowser-cutplan.svg
```

The output keeps the export's inch size and pages and has one Inkscape layer per pass plus a hidden Review layer drawing the lifted moves; `bowser-cutplan.log` keeps the console output (written as it runs) and `bowser-cutplan.csv` lists travel and cut length per sheet and pass, before and after. The solver is a generalised TSP: Gurobi when `gurobipy` is installed (exact, warm-started, `--time-limit` seconds per pass and sheet), otherwise nearest neighbour + 2-opt with an exact choice of start points. The pip size-limited Gurobi licence only fits the smallest sheets and falls back to the heuristic on the rest. `--stay-down` then marks the offcuts worth saving and keeps the blade down on moves that can run through waste (thin strips and leftovers between pieces), never through a piece, a saved offcut or for folds. For one Cricut upload it writes `bowser-cutplan-cricut.svg` (or `--cricut FILE`): every sheet side by side, one row per cardstock colour, each sheet a group (`P04-red`) of up to four compound paths named `cut`, `deboss-valley`, `score-mountain` and `draw`. It also writes one SVG per sheet into `bowser-cutplan-sheets/` (or `--sheets DIR`) for Cricut import: one compound path per tool (Cut = fine-point blade, Fold valley = debossing tip, Fold mountain = double scoring wheel, Draw = pen), no groups, subpaths in the planned order, each outline starting at its planned corner and written open (no `Z`) back to that corner.

## Glue tabs and protected piece bodies

Low-poly papercraft pieces have glue tabs that are hidden in the assembled model. Those tabs may be trimmed when nesting requires it, but the visible main body must remain intact. A future tab-aware mode will need the converter to label body and tab geometry separately, preserve a configurable safety margin around the body (about 2–3 mm to start), and trim only tab cut paths where needed to prevent cut paths from overlapping. The current converter handoff does not yet carry that distinction, so tab trimming is not enabled.

## Cricut handoff

The output is a single SVG document with one Inkscape page for each stock sheet, grouped by cardstock color and preserving each source piece's operation groups and annotations. Piece IDs/material IDs remain in SVG attributes and layer labels. Cricut Design Space behavior for Inkscape multi-page documents and operation assignment must be checked in the target app before cutting; SVG import can map vectors to cut operations, so inspect and assign score/draw operations in Design Space as needed. Cricut also documents a 5,000-path upload limit.

The converter handoff is intentionally based on the current SVG group structure plus YAML material pages. Keep the pinned converter revision in the models repository and this parser aligned as the converter finalizes its piece-group export contract. Each complete piece should remain a single independently positioned group so Cricut receives the intended geometry instead of naively merging neighboring pieces.
