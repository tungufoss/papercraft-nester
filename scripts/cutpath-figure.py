"""Before/after figure of the cutpath passes on one sheet of an export SVG.

    PYTHONPATH=src python scripts/cutpath-figure.py examples/example-export.svg img/cutpath-example.svg

Rows: Cut, Fold valley, Fold mountain (a pass with no lines is left out). Left: source order (pieces and lines as they come in the
file, each outline from its first vertex). Right: the planned route. Cut is solid, valley dashed,
mountain dash-dot (the template styles in the YAML); lifted travel is dotted.
"""
from __future__ import annotations
import sys
from pathlib import Path
from papercraft_nester.cutpath import ExportFile, path_d
from papercraft_nester.route import HeuristicRouter

STYLE = {"cut": ("Cut", "#000000", "none"), "valley": ("Fold valley", "#2e8b57", "2,1.2"),
         "mountain": ("Fold mountain", "#1f5fbf", "3,1,0.5,1")}
TRAVEL = "#d6336c"


def moves(lines_per_job, home):
    out, pos = [], home
    for lines in lines_per_job:
        for line in lines:
            if pos != line[0]:
                out.append([pos, line[0]])
            pos = line[-1]
    return out


def main(src: Path, dst: Path, page: int | None = None) -> None:
    doc = ExportFile(src)
    sheet = doc.sheets[page] if page else min(doc.sheets.values(), key=lambda s: s.page)
    sheet.plan(HeuristicRouter(), 0.35)
    home = sheet.origin
    pts = [p for piece in sheet.pieces for p in piece.rings[0]] + [home]
    x0, y0 = min(p[0] for p in pts) - 3, min(p[1] for p in pts) - 3
    w, h = max(p[0] for p in pts) + 3 - x0, max(p[1] for p in pts) + 3 - y0
    kinds = [k for k in STYLE if next(p for p in sheet.passes if p.kind == k).jobs]  # skip empty passes
    head, gap = 9.0, 6.0
    W, H = 2 * w + gap, len(kinds) * (h + head)
    body = []
    outline = path_d([piece.rings[0] + [piece.rings[0][0]] for piece in sheet.pieces])
    for row, kind in enumerate(kinds):
        name, colour, dash = STYLE[kind]
        p = next(p for p in sheet.passes if p.kind == kind)
        before = [job.options[0] for job in p.jobs]
        for col, (title, lines, length) in enumerate([("source order", before, p.source_travel),
                                                      ("planned", p.lines, p.travel)]):
            ox, oy = col * (w + gap) - x0, row * (h + head) + head - y0
            body.append(f'<text x="{col * (w + gap) + 1:.1f}" y="{row * (h + head) + head - 2.5:.1f}" '
                        f'font-size="4.2">{name}, {title}: travel {length / 1000:.2f} m</text>')
            body.append(f'<g transform="translate({ox:.2f} {oy:.2f})">')
            body.append(f'<path d="{outline}" fill="#f4f1ea" stroke="#c8c2b6" stroke-width="0.25"/>')
            drawn = path_d([line for job in lines for line in job])
            body.append(f'<path d="{drawn}" fill="none" stroke="{colour}" stroke-width="0.45" '
                        f'stroke-dasharray="{dash}" stroke-linecap="round" stroke-linejoin="round"/>')
            body.append(f'<path d="{path_d(moves(lines, home))}" fill="none" stroke="{TRAVEL}" '
                        f'stroke-width="0.6" stroke-dasharray="0.1,1.2" stroke-linecap="round"/>')
            body.append(f'<circle cx="{home[0]}" cy="{home[1]}" r="1.2" fill="{TRAVEL}"/></g>')
    dst.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.1f} {H:.1f}" '
                   f'width="{W * 4:.0f}" height="{H * 4:.0f}" font-family="Arial,sans-serif">'
                   f'<rect width="100%" height="100%" fill="#ffffff"/>{"".join(body)}</svg>\n', encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else None)
