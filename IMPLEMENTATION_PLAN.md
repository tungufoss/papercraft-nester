# Implementation Plan: papercraft-nester

**Goal:** Build a separate optimizer that consumes converter outputs and produces one Cricut-oriented SVG master containing all nested cardstock sheets.

**Architecture:** A Python CLI reads the converter's Inkscape SVG and YAML material mapping, extracts each labeled piece as a local group, and nests it on finite per-color sheet inventory. A writer transforms complete piece groups (cut, mountain fold, valley fold, and number drawing together) onto Inkscape pages inside one SVG and reports sheet counts/utilization/travel for the Letter benchmark. Converter handoff must eventually identify each piece's protected body separately from its glue tabs.

**Files touched:**
- `README.md` — handoff contract, install/run instructions, known Cricut constraints.
- `pyproject.toml` — package metadata and CLI entry point.
- `src/papercraft_nester/__init__.py` — package marker.
- `src/papercraft_nester/cli.py` — arguments and orchestration.
- `src/papercraft_nester/converter.py` — parse current SVG/YAML handoff and extract piece geometry/operations.
- `src/papercraft_nester/geometry.py` — polygon transforms, collision, gap, and candidate placement helpers.
- `src/papercraft_nester/nesting.py` — finite mixed-size inventory and free-rotation nesting.
- `src/papercraft_nester/svg.py` — single SVG master output with material color and preserved operations.
- `src/papercraft_nester/report.py` — per-color/sheet counts, utilization, and travel metrics.
- `config/bowser-letter.json` — editable finite inventory seed based on current source pages.
- `tests/` — focused geometry, inventory, converter parsing, and output smoke tests.

## Tasks

### Batch 1 — Tracer bullet
1. Add package skeleton and CLI to read the current Bowser SVG, YAML, and inventory; report extracted piece/material counts. Add a smoke test using a small SVG fixture.
2. Confirm current source data yields 178 pieces and material counts from the manifest without touching `cricut-masks`.

### Batch 2 — Nesting core
3. Add polygon extraction and rigid transforms for the source's closed polygon outlines.
4. Add non-overlap + configurable gap placement, arbitrary rotation candidates with local angle refinement, and finite mixed-size sheets per material. Add focused geometry/inventory tests.

### Batch 3 — SVG and benchmark
5. Write one master SVG with one Inkscape page per physical sheet, preserving each piece's operation groups and material color; add a single-file output smoke test.
6. Run the Letter benchmark using editable inventory seeded from source page counts; compare sheet counts/utilization to the original page layout and provide travel estimates.

**Priority:** minimum sheets, then material utilization, then estimated tool travel. The initial mode packs complete outlines with a configurable gap. A later tab-aware mode may overlap/trim glue tabs: the piece body remains protected by a configurable 2–3 mm margin, while tab material may be cut away as needed to avoid overlapping cut paths. Tabs are functional glue flaps but are not part of the visible mask surface. This requires the converter export to distinguish tab geometry from the main body; do not infer trim-safe areas from a single undifferentiated outline.

**Open constraint:** Cricut Design Space imports SVG vectors as cut geometry; confirm operation mapping and multi-page handling in the application before describing the master as directly cut-ready.
