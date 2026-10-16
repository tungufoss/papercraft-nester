# GitHub issue drafts

These drafts reflect the current project decisions. Apply the destination repository's existing labels when creating them; labels below are suggestions, not assumed to exist.

## 1. Define a stable converter-to-nester piece contract

**Suggested labels:** `enhancement`, `converter-integration`

The nester needs a machine-readable handoff from `lowpoly-pdf-to-svg` that preserves complete piece groups and exposes their fabrication meaning. Specify piece ID, cardstock material/color, page, cut paths, mountain folds, valley folds, and pen annotations. The later tab-aware mode also requires explicit protected-body and glue-tab geometry. Keep the converter and nester contract versioned and testable together.

**Acceptance criteria**
- Every fabrication piece has a stable ID and material assignment.
- All cut/fold/draw paths belonging to a piece remain in one independently transformable group.
- The ordinary outline is available for current no-overlap nesting.
- Body and tab regions can be represented separately before tab trimming is enabled.
- Document units and source-page offsets are explicit.

## 2. Add a solver adapter and benchmark PackingSolver

**Suggested labels:** `enhancement`, `optimization`, `research`

The current Python placement heuristic has not improved on the source Bowser layout. Add a repository-owned solver interface that accepts normalized piece polygons and finite sheet inventory and returns placements only. Evaluate PackingSolver's irregular solver as the primary candidate, while retaining the current heuristic as a baseline/comparison until the candidate produces valid Bowser layouts on the supported Windows/Python environment.

**Acceptance criteria**
- Solver dependencies and supported Python/platform requirements are documented.
- Adapter returns piece ID, material, sheet, position, and rotation without changing source SVG geometry.
- Mirroring is disabled.
- Compare source layout, current heuristic, and PackingSolver on the same Letter instance and time budget.
- Independently validate all returned placements before SVG export; invalid or incomplete results are rejected.

## 3. Implement color-specific finite-stock nesting and the chosen objective

**Suggested labels:** `enhancement`, `nesting`, `geometry`

Solve each cardstock color independently using only the finite inventory entered for that color. Permit mixed sheet sizes for a color and rigid rotation. For the current mode, require complete piece outlines to fit without overlap and honor a configurable minimum gap. Rank plans lexicographically: fewest sheets first, then best utilization, then least estimated cutter travel. This ordering is the project decision even when stock sheet sizes differ.

**Acceptance criteria**
- Inventory rows include material/color, dimensions, and available quantity.
- A piece is assigned exactly once and only to stock of its material.
- No piece is mirrored, clipped, overlapped, or placed outside its sheet.
- Configurable minimum clearance is validated geometrically.
- Reports include sheet count by color and size, utilization/waste, and estimated travel.

## 4. Export and validate one project-wide multi-page SVG

**Suggested labels:** `enhancement`, `svg`, `cricut`

Export one master SVG with one Inkscape page per physical sheet. Use the cardstock color on each piece so pieces on different colors separate naturally in Cricut. Apply the solver placement as one rigid transform to the original piece group, preserving all cut, mountain-fold, valley-fold, and annotation paths and stable IDs. Do not flatten distinct operations into the nesting polygon.

**Acceptance criteria**
- One output file contains all colors and sheets, with an identifiable page for every physical sheet.
- Each piece group keeps its cardstock color and source ID.
- Every original operation path receives the same placement transform.
- Output geometry stays within each page and has the expected physical dimensions.
- Output reopens in Inkscape and is manually checked in Cricut Design Space before cutting.

## 5. Add a protected-body, trimmable-glue-tab mode

**Suggested labels:** `enhancement`, `geometry`, `future`

After the converter exports body and glue-tab regions separately, add an opt-in nesting mode that permits sacrificial tabs to overlap and be trimmed while protecting the visible body. Start with a configurable 2–3 mm protected-body margin. Regenerate cut paths from retained geometry so tabs are trimmed without cutting into a protected body or leaving overlapping cut paths.

**Acceptance criteria**
- Disabled by default until body/tab geometry is explicit and validated.
- Only tab regions may be trimmed; body geometry remains intact with the configured margin.
- Trimmed output has no duplicate/internal overlapping cut segments.
- Visual and geometric checks cover tab-tab collisions, tab-body proximity, and sheet boundaries.
- The SVG retains folds and annotations for the untrimmed body.

## 6. Benchmark Letter layouts and validate cutter-travel assumptions

**Suggested labels:** `benchmark`, `cricut`, `optimization`

Use the original Bowser Letter page assignment as the first benchmark. Compare nesting quality and travel estimates with the original PDF/source layout, then add A4 and mixed-size inventory experiments. Before treating path ordering as a Cricut time optimization, verify whether the current Design Space version honors imported SVG element order; otherwise present travel as an estimate only.

**Acceptance criteria**
- Record source and packed sheet counts, utilization/waste, runtime, and travel estimate.
- Run Letter first; add A4 and mixed Letter/A4 as follow-up comparisons.
- Preserve a repeatable solver seed/time budget for fair comparisons.
- Verify actual Cricut cut order with a small numbered test and record the Design Space version and result.
- Do not claim reduced Cricut travel unless the app follows the exported path order in the test.

## 7. Build the user guide and Python package documentation

**Suggested labels:** `documentation`, `area: docs-site`

Create the practical documentation site for installing and using papercraft-nester. The project-facing interface is Python, so document its CLI and Python package/API; the C++ solver can remain behind the adapter unless later evidence makes a C++ interface more useful. Explain the converter handoff, material colors, finite mixed-size stock inventory, clearance, rotations, output SVG pages, and how to inspect the result in Inkscape and Cricut Design Space.

**Acceptance criteria**
- A new user can install the package and run the Bowser Letter example from documented steps.
- Document the SVG/YAML handoff and current limitations, including that tab trimming is not enabled.
- Include Python examples for the supported CLI/API and explain solver backend selection.
- Add navigation links to the working paper and benchmark results.

## 8. Start a working paper with the HÍ `quarto-hi` article template

**Suggested labels:** `documentation`, `area: research-paper`

Create `paper/` as a Quarto article using the Documents & Kynningar / `HI-IDN/quarto-hi` template already used by the converter repository. Start with the problem formulation, fabrication constraints, solver/backend comparison, objective ordering, evaluation metrics, and reproducible Bowser Letter benchmark plan. Keep measured results clearly separate from planned experiments; do not invent benchmark results.

**Acceptance criteria**
- HTML article and PDF render from the Quarto project with the `quarto-hi` style.
- References, citations, author/title metadata, and template assets are configured.
- Draft describes the current objective (fewest sheets, then utilization, then travel) and protected-body/tab model accurately.
- Research questions, methods, and results can be edited as a normal QMD manuscript.

## 9. Publish the documentation site and paper with GitHub Actions Pages

**Suggested labels:** `enhancement`, `area: docs-site`, `area: research-paper`

Add a GitHub Actions workflow that builds the practical user documentation and the `quarto-hi` article, then publishes both under the same GitHub Pages site with clear navigation between them. Keep generated source-PDF-dependent Bowser assets out of the public artifact unless they are explicitly cleared for redistribution.

**Acceptance criteria**
- Workflow renders docs and paper on pushes to the chosen publishing branch and supports manual runs.
- A failed render fails the workflow rather than deploying a partial site.
- One Pages deployment contains the user guide/API documentation and the working-paper HTML/PDF.
- Public site output excludes private source PDFs and unapproved generated Bowser cut geometry.
