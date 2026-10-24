"""Cut / fold / pen path planning per cardstock sheet, pieces left where they are.

Reads a `lowpoly-export/1` SVG. A sheet is one source page. On each sheet four passes are ordered
on their own: Cut (one job per piece; a piece is always cut in one go, edges a neighbour already cut
are skipped), Fold valley and Fold mountain (one job per fold line, either direction) and Draw
(the short labels in a single-stroke pen font).
"""
from __future__ import annotations
import csv
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from .font import text_strokes
from .route import Job, Point, dist, travel

SVG = "http://www.w3.org/2000/svg"
INK = "http://www.inkscape.org/namespaces/inkscape"
SODI = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
ET.register_namespace("", SVG)
ET.register_namespace("inkscape", INK)
ET.register_namespace("sodipodi", SODI)
NUM = r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"
PASSES = [("cut", "Cut", "#000000"), ("valley", "Fold valley", "#2e8b57"),
          ("mountain", "Fold mountain", "#1f5fbf"), ("draw", "Draw", "#444444")]


def rings(d: str) -> list[list[Point]]:
    """Closed polygons of an `M x,y x,y ... Z` compound path (outline first, then holes)."""
    out = []
    for part in re.findall(r"[Mm]([^MmZz]*)", d):
        v = [float(n) for n in re.findall(NUM, part)]
        pts = list(zip(v[::2], v[1::2]))
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts.pop()
        if len(pts) >= 3:
            out.append(pts)
    return out


def length(lines: list[list[Point]]) -> float:
    return sum(dist(a, b) for line in lines for a, b in zip(line, line[1:]))


@dataclass
class Piece:
    id: str
    material: str
    rings: list[list[Point]]
    folds: dict[str, list[tuple[Point, Point]]]
    labels: list[list[list[Point]]]  # label -> pen strokes


@dataclass
class Pass:
    kind: str
    jobs: list[Job]
    route: list[tuple[int, int]]
    lines: list[list[list[Point]]]  # per routed job, the polylines actually drawn
    source_travel: float
    travel: float
    source_length: float
    length: float
    strokes: list[tuple[list[str], list[Point]]] = field(default_factory=list)  # tool-down runs

    def join(self, rings: list[list[Point]], stay_down: float, home: Point) -> None:
        """Tool-down runs: consecutive polylines are joined when the move between them is at most
        `stay_down` mm and stays in the offcut (a thin strip between pieces, never across one)."""
        self.strokes, pos = [], home
        for (j, _), lines in zip(self.route, self.lines):
            for line in lines:
                if self.strokes and dist(pos, line[0]) <= stay_down and offcut(pos, line[0], rings):
                    names, run = self.strokes[-1]
                    run.extend(line if dist(pos, line[0]) > 1e-9 else line[1:])
                    if self.jobs[j].name not in names:
                        names.append(self.jobs[j].name)
                else:
                    self.strokes.append(([self.jobs[j].name], list(line)))
                pos = line[-1]

    @property
    def offcut_length(self) -> float:
        inner = sum(length([run]) for _, run in self.strokes)
        return max(0.0, inner - self.length)


@dataclass
class Sheet:
    page: int
    material: str
    origin: Point
    pieces: list[Piece] = field(default_factory=list)
    passes: list[Pass] = field(default_factory=list)

    def plan(self, router, share_tol: float, stay_down: float = 0.0) -> "Sheet":
        home = self.origin
        cut = [Job.loop(p.id, p.rings[0]) for p in self.pieces]
        self.passes = [self._cut_pass(cut, router.solve(cut, home), home, share_tol)]
        for kind in ("valley", "mountain"):
            jobs = [Job.line(p.id, a, b) for p in self.pieces for a, b in p.folds[kind]]
            self.passes.append(self._simple_pass(kind, jobs, router.solve(jobs, home), home))
        jobs = [Job.strokes(p.id, strokes) for p in self.pieces for strokes in p.labels]
        self.passes.append(self._simple_pass("draw", jobs, router.solve(jobs, home), home))
        outlines = [p.rings[0] for p in self.pieces]
        for p in self.passes:
            p.join(outlines, stay_down if p.kind == "cut" else 0.0, home)  # folds and labels always lift
        return self

    def _cut_pass(self, jobs, route, home, tol):
        holes = {p.id: p.rings[1:] for p in self.pieces}
        done: list[tuple[Point, Point]] = []
        drawn = []
        for j, k in route:
            # Holes first so the piece is still held by the sheet while they are cut.
            lines = [h + [h[0]] for h in holes[jobs[j].name]] + trim(jobs[j].options[k][0], done, tol)
            done += [(a, b) for line in lines for a, b in zip(line, line[1:])]
            drawn.append(lines)
        source = [(j, 0) for j in range(len(jobs))]
        full = sum(length(job.options[0]) for job in jobs) + sum(length([h + [h[0]]]) for hs in holes.values() for h in hs)
        return Pass("cut", jobs, route, drawn, travel(jobs, source, home), path_travel(drawn, home),
                    full, sum(length(lines) for lines in drawn))

    @staticmethod
    def _simple_pass(kind, jobs, route, home):
        drawn = [jobs[j].options[k] for j, k in route]
        size = sum(length(job.options[0]) for job in jobs)
        return Pass(kind, jobs, route, drawn, travel(jobs, [(j, 0) for j in range(len(jobs))], home),
                    path_travel(drawn, home), size, size)


def path_travel(drawn: list[list[list[Point]]], home: Point) -> float:
    """Lifted travel between consecutive polylines, including gaps inside one job."""
    pos, total = home, 0.0
    for lines in drawn:
        for line in lines:
            total += dist(pos, line[0])
            pos = line[-1]
    return total


def inside(p: Point, ring: list[Point]) -> bool:
    x, y, odd = p[0], p[1], False
    for (x1, y1), (x2, y2) in zip(ring[-1:] + ring[:-1], ring):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            odd = not odd
    return odd


def offcut(a: Point, b: Point, rings: list[list[Point]], step: float = 0.2, margin: float = 0.15) -> bool:
    """True when the straight move a->b runs only through paper outside every piece, keeping
    `margin` mm from all outlines except near its two ends (which sit on outlines)."""
    L = dist(a, b)
    for i in range(1, max(2, int(L / step))):
        t = i / max(2, int(L / step))
        p = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        if any(inside(p, r) for r in rings):
            return False
        if min(t, 1 - t) * L > 2 * margin and any(line_gap(p, r[k - 1], r[k]) < margin for r in rings for k in range(len(r))):
            return False
    return True


def trim(loop: list[Point], done: list[tuple[Point, Point]], tol: float) -> list[list[Point]]:
    """The parts of a closed polyline not lying within `tol` of an already cut segment, as
    polylines in the same order. Overlap needs near-parallel segments (within ~5 degrees)."""
    out: list[list[Point]] = []
    for a, b in zip(loop, loop[1:]):
        L = dist(a, b)
        if L == 0:
            continue
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        covered = []
        for c, e in done:
            M = dist(c, e)
            if M == 0 or abs(ux * (e[1] - c[1]) - uy * (e[0] - c[0])) / M > 0.087:
                continue
            tc = ((c[0] - a[0]) * ux + (c[1] - a[1]) * uy) / L
            te = ((e[0] - a[0]) * ux + (e[1] - a[1]) * uy) / L
            lo, hi = max(0.0, min(tc, te)), min(1.0, max(tc, te))
            if hi <= lo:
                continue
            p, q = (a[0] + lo * L * ux, a[1] + lo * L * uy), (a[0] + hi * L * ux, a[1] + hi * L * uy)
            if line_gap(p, c, e) <= tol and line_gap(q, c, e) <= tol:
                covered.append((lo, hi))
        t = 0.0
        for lo, hi in sorted(covered) + [(1.0, 1.0)]:
            if lo - t > 1e-9 and (lo - t) * L > tol:
                p, q = (a[0] + t * L * ux, a[1] + t * L * uy), (a[0] + lo * L * ux, a[1] + lo * L * uy)
                if out and dist(out[-1][-1], p) < 1e-9:
                    out[-1].append(q)
                else:
                    out.append([p, q])
            t = max(t, hi)
    if len(out) > 1 and dist(out[-1][-1], out[0][0]) < 1e-9:
        out[0] = out.pop() + out[0][1:]  # the loop's last part runs straight into its first
    return out


def line_gap(p: Point, a: Point, b: Point) -> float:
    """Distance from p to the segment ab."""
    L2 = (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2
    t = max(0.0, min(1.0, ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / L2))
    return dist(p, (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))


class ExportFile:
    """The pieces of a lowpoly-export/1 SVG, grouped into sheets (source pages)."""

    def __init__(self, path: Path):
        self.tree = ET.parse(path)
        root = self.tree.getroot()
        if root.get("data-contract") != "lowpoly-export/1":
            raise ValueError(f"{path}: not a lowpoly-export/1 file")
        self.root, self.sheets = root, {}
        for g in root.iter(f"{{{SVG}}}g"):
            if g.get("data-piece"):
                self._add(g)
        if not self.sheets:
            raise ValueError(f"{path}: no pieces")

    def _add(self, g):
        page = int(g.get("data-source-page"))
        ox, oy = (float(v) for v in g.get("data-page-origin-mm", "0 0").split())
        sheet = self.sheets.setdefault(page, Sheet(page, g.get("data-material"), (ox, oy)))
        cut = next(e for e in g.iter(f"{{{SVG}}}path") if e.get("data-operation") == "cut")
        folds = {"valley": [], "mountain": []}
        for e in g.iter(f"{{{SVG}}}path"):
            if e.get("data-operation") == "score":
                v = [float(n) for n in re.findall(NUM, e.get("d"))]
                folds[e.get("data-fold", "valley")].append(((v[0], v[1]), (v[-2], v[-1])))
        labels = []
        for t in g.iter(f"{{{SVG}}}text"):
            if t.get("data-operation") != "draw":
                continue
            rot = re.search(rf"rotate\(\s*({NUM})", t.get("transform", ""))
            labels.append(text_strokes(t.get("data-label") or (t.text or "").strip(), float(t.get("x")),
                                       float(t.get("y")), float(t.get("font-size", "2")),
                                       float(rot.group(1)) if rot else 0.0))
        sheet.pieces.append(Piece(g.get("data-piece"), g.get("data-material"), rings(cut.get("d")), folds, labels))

    def write(self, path: Path) -> None:
        root = ET.Element(f"{{{SVG}}}svg", {k: v for k, v in self.root.attrib.items() if k != "data-contract"})
        root.set("data-plan", "lowpoly-cutplan/1")
        for view in self.root.iter(f"{{{SODI}}}namedview"):
            root.append(view)
        sheets = sorted(self.sheets.values(), key=lambda s: s.page)
        for kind, name, colour in PASSES:
            layer = ET.SubElement(root, f"{{{SVG}}}g", {"id": f"layer-{kind}", f"{{{INK}}}groupmode": "layer",
                                                       f"{{{INK}}}label": name,
                                                       "style": f"fill:none;stroke:{colour};stroke-width:0.25;stroke-linecap:round;stroke-linejoin:round"})
            for sheet in sheets:
                p = next(p for p in sheet.passes if p.kind == kind)
                group = ET.SubElement(layer, f"{{{SVG}}}g", {"id": f"{kind}-page-{sheet.page:02d}",
                                                            f"{{{INK}}}label": f"Page {sheet.page:02d} · {sheet.material}",
                                                            "data-source-page": str(sheet.page)})
                for order, (names, run) in enumerate(p.strokes, 1):
                    ET.SubElement(group, f"{{{SVG}}}path", {"d": path_d([run]), "data-piece": " ".join(names),
                                                            "data-order": str(order), "data-operation": kind})
        review = ET.SubElement(root, f"{{{SVG}}}g", {"id": "layer-review", f"{{{INK}}}groupmode": "layer",
                                                    f"{{{INK}}}label": "Review", "style": "display:none"})
        for sheet in sheets:
            for p in sheet.passes:
                moves, pos = [], sheet.origin
                for lines in p.lines:
                    for line in lines:
                        if dist(pos, line[0]) > 1e-6:
                            moves.append([pos, line[0]])
                        pos = line[-1]
                if moves:
                    ET.SubElement(review, f"{{{SVG}}}path", {
                        "d": path_d(moves), "data-source-page": str(sheet.page), "data-operation": f"{p.kind}-travel",
                        "style": "fill:none;stroke:#e040fb;stroke-width:0.15;stroke-dasharray:1,1"})
        ET.indent(root)
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)

    def report(self, path: Path) -> list[dict]:
        rows = [{"page": s.page, "material": s.material, "pass": p.kind, "jobs": len(p.jobs),
                 "travel_source_mm": round(p.source_travel, 1), "travel_mm": round(p.travel, 1),
                 "length_source_mm": round(p.source_length, 1), "length_mm": round(p.length, 1),
                 "lifts": len(p.strokes), "offcut_mm": round(p.offcut_length, 1),
                 "order": " ".join(dict.fromkeys(p.jobs[j].name for j, _ in p.route))}
                for s in sorted(self.sheets.values(), key=lambda s: s.page) for p in s.passes]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return rows


def path_d(lines: list[list[Point]]) -> str:
    return " ".join("M " + " ".join(f"{x:.3f},{y:.3f}" for x, y in line) for line in lines)


def plan(export: Path, output: Path, table: Path, router, share_tol: float = 0.35, stay_down: float = 0.0,
         log=print) -> list[dict]:
    doc = ExportFile(export)
    for sheet in sorted(doc.sheets.values(), key=lambda s: s.page):
        sheet.plan(router, share_tol, stay_down)
        log(f"page {sheet.page:02d} {sheet.material:<7} " + " | ".join(
            f"{p.kind} {p.source_travel:.0f}->{p.travel:.0f} mm" for p in sheet.passes))
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.write(output)
    return doc.report(table)
