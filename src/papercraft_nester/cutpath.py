"""Cut / fold / pen path planning per cardstock sheet, pieces left where they are.

Reads a `lowpoly-export/1` SVG. A sheet is one source page. On each sheet four passes are ordered
on their own: Cut (one job per piece; a piece is always cut in one go, edges a neighbour already cut
are skipped), Fold valley and Fold mountain (one job per fold line, either direction) and Draw
(the short labels in a single-stroke pen font).
"""
from __future__ import annotations
import csv
import heapq
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from shapely.geometry import LineString, Point as ShapelyPoint, Polygon, box
from shapely.prepared import prep
from shapely.ops import unary_union
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
    bridges: list[list[Point]] = field(default_factory=list)  # blade-down moves through waste

    def join(self, waste: "Waste | None", home: Point) -> None:
        """Tool-down runs: consecutive polylines are joined when the move between them runs only
        through waste paper (see Waste.path); without a Waste every move lifts."""
        self.strokes, self.bridges, pos = [], [], home
        for (j, _), lines in zip(self.route, self.lines):
            for line in lines:
                if not self.strokes:
                    bridge = None
                elif dist(pos, line[0]) < 1e-9:
                    bridge = [pos, pos]  # the next line starts where this one ends: no move at all
                else:
                    bridge = waste.path(pos, line[0]) if waste else None
                if bridge:
                    if len(bridge) > 1 and dist(bridge[0], bridge[-1]) > 1e-9:
                        self.bridges.append(bridge)
                        waste.commit(bridge)
                    names, run = self.strokes[-1]
                    run.extend(bridge[1:-1] + (line if dist(pos, line[0]) > 1e-9 else line[1:]))
                    if self.jobs[j].name not in names:
                        names.append(self.jobs[j].name)
                else:
                    self.strokes.append(([self.jobs[j].name], list(line)))
                pos = line[-1]

    @property
    def recut_length(self) -> float:
        """Length (mm) the tool would go over a second time; the plan keeps this at 0."""
        done, total = [], 0.0
        for _, run in self.strokes:
            for a, b in zip(run, run[1:]):
                if dist(a, b) > 1e-9:
                    total += dist(a, b) - length(trim([a, b], done, 0.05))
                    done.append((a, b))
        return total

    @property
    def offcut_length(self) -> float:
        inner = sum(length([run]) for _, run in self.strokes)
        return max(0.0, inner - self.length)


@dataclass
class Sheet:
    page: int
    material: str
    origin: Point
    size: Point = (0.0, 0.0)
    pieces: list[Piece] = field(default_factory=list)
    passes: list[Pass] = field(default_factory=list)
    waste: "Waste | None" = None

    def plan(self, router, share_tol: float, stay_down: float = 0.0, min_width: float = 20.0,
             min_area: float = 50.0, detour: float = 1.5) -> "Sheet":
        home = self.origin
        cut = [Job.loop(p.id, p.rings[0]) for p in self.pieces]
        self.passes = [self._cut_pass(cut, router.solve(cut, home), home, share_tol)]
        for kind in ("valley", "mountain"):
            jobs = [Job.line(p.id, a, b) for p in self.pieces for a, b in p.folds[kind]]
            self.passes.append(self._simple_pass(kind, jobs, router.solve(jobs, home), home))
        jobs = [Job.strokes(p.id, strokes) for p in self.pieces for strokes in p.labels]
        self.passes.append(self._simple_pass("draw", jobs, router.solve(jobs, home), home))
        sheet = box(self.origin[0], self.origin[1], self.origin[0] + self.size[0], self.origin[1] + self.size[1])
        self.waste = (Waste([p.rings[0] for p in self.pieces], sheet, stay_down, min_width, min_area, detour)
                      if stay_down > 0 else None)
        for p in self.passes:
            p.join(self.waste if p.kind == "cut" else None, home)  # folds and labels always lift
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


class Waste:
    """Step 2 and 3 of the cut plan, after the shortest lifted route.

    Saved offcuts: the sheet minus the pieces closed over every gap or notch narrower than `strip`
    mm, with every part narrower than `min_width` mm shaved off, keeping pieces of at least
    `min_area` cm². Everything else that is not a piece is waste:
    thin strips, notches, sheet edges and small leftovers. The blade may cut through waste but never
    into a saved offcut or a piece, so a move stays blade-down when a path through waste exists that
    is at most `detour` times the straight move (straight if possible, else around pieces).
    A path never runs along an outline or an earlier path: away from its two ends it keeps `gap` mm
    from every piece and from every path already cut, so no line is cut twice."""

    def __init__(self, rings: list[list[Point]], sheet: Polygon, strip: float, min_width: float = 20.0,
                 min_area: float = 50.0, detour: float = 1.5, margin: float = 0.15, gap: float = 0.3):
        pieces = unary_union([Polygon(r).buffer(0) for r in rings])
        closed = pieces.buffer(strip / 2).buffer(-strip / 2)
        rest = sheet.difference(closed)
        # Shrinking by half the width cuts every neck narrower than it, so each part that is left
        # grows back (round corners, no spikes) into its own offcut piece; the necks become waste.
        cores = rest.buffer(-min_width / 2)
        self.saved, taken = [], Polygon()
        for core in sorted(getattr(cores, "geoms", [cores]), key=lambda g: -g.area):
            part = core.buffer(min_width / 2).intersection(rest).difference(taken)
            part = max(getattr(part, "geoms", [part]), key=lambda g: g.area, default=Polygon())
            if part.area >= 100 * min_area:
                self.saved.append(part)
                taken = taken.union(part)
        self.region = sheet.difference(unary_union(self.saved)).buffer(1e-6) if self.saved else sheet.buffer(1e-6)
        self.core = pieces.buffer(-margin)  # a move may touch an outline, never enter a piece
        self.gap, self.keepout, self.cut = gap, pieces.buffer(gap), Polygon()
        self._region, self._core, self._keepout = prep(self.region), prep(self.core), prep(self.keepout)
        free = self.region.difference(pieces.buffer(2 * gap)).simplify(0.1)
        self.nodes = [p for g in getattr(free, "geoms", [free]) for ring in [g.exterior, *g.interiors]
                      for p in ring.coords[:-1]]
        self.detour = detour

    def allows(self, a: Point, b: Point, ends: tuple[Point, ...] = ()) -> bool:
        """Is a -> b a legal blade-down move? `ends` are the path's own end points (on outlines),
        the only places where it may come close to a piece or an earlier path."""
        if dist(a, b) < 1e-9:
            return True
        move = LineString([a, b])
        if not self._region.covers(move) or self._core.intersects(move):
            return False
        away = move.difference(unary_union([ShapelyPoint(*e).buffer(4 * self.gap) for e in ends])) if ends else move
        return away.is_empty or not (self._keepout.intersects(away) or self.cut.intersects(away))

    def commit(self, bridge: list[Point]) -> None:
        """Remember a path that will be cut, so later paths keep clear of it."""
        self.cut = self.cut.union(LineString(bridge).buffer(self.gap))

    def path(self, a: Point, b: Point) -> list[Point] | None:
        """Shortest blade-down path a -> b through waste (visibility graph), or None."""
        if self.allows(a, b, (a, b)):
            return [a, b]
        limit = self.detour * dist(a, b)
        nodes = [a, b] + [p for p in self.nodes if dist(a, p) + dist(p, b) <= limit]
        best, prev, todo = {0: 0.0}, {}, [(0.0, 0)]
        while todo:
            d, u = heapq.heappop(todo)
            if u == 1:
                out = [b]
                while u in prev:
                    u = prev[u]
                    out.append(nodes[u])
                return out[::-1]
            if d > best.get(u, math.inf):
                continue
            for v in range(1, len(nodes)):
                nd = d + dist(nodes[u], nodes[v])
                if nd < best.get(v, math.inf) and nd + dist(nodes[v], b) <= limit and self.allows(nodes[u], nodes[v], (a, b)):
                    best[v], prev[v] = nd, u
                    heapq.heappush(todo, (nd, v))
        return None

    def outline(self, polys) -> list[list[Point]]:
        return [list(ring.coords) for poly in polys for ring in [poly.exterior, *poly.interiors]]


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
        self.pages = {int(re.search(r"(\d+)$", e.get("id")).group(1)): (float(e.get("width")), float(e.get("height")))
                      for e in root.iter(f"{{{INK}}}page") if re.search(r"\d+$", e.get("id", ""))}
        for g in root.iter(f"{{{SVG}}}g"):
            if g.get("data-piece"):
                self._add(g)
        if not self.sheets:
            raise ValueError(f"{path}: no pieces")

    def _add(self, g):
        page = int(g.get("data-source-page"))
        ox, oy = (float(v) for v in g.get("data-page-origin-mm", "0 0").split())
        sheet = self.sheets.setdefault(page, Sheet(page, g.get("data-material"), (ox, oy), self.pages.get(page, (215.9, 279.4))))
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
            if sheet.waste and sheet.waste.saved:
                ET.SubElement(review, f"{{{SVG}}}path", {
                    "d": path_d(sheet.waste.outline(sheet.waste.saved)) + " Z", "data-source-page": str(sheet.page),
                    "data-operation": "saved-offcut", "style": "fill:#40c057;fill-opacity:0.15;stroke:#2b8a3e;stroke-width:0.2"})
        ET.indent(root)
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)

    def report(self, path: Path) -> list[dict]:
        rows = [{"page": s.page, "material": s.material, "pass": p.kind, "jobs": len(p.jobs),
                 "travel_source_mm": round(p.source_travel, 1), "travel_mm": round(p.travel, 1),
                 "length_source_mm": round(p.source_length, 1), "length_mm": round(p.length, 1),
                 "lifts": len(p.strokes), "waste_cut_mm": round(p.offcut_length, 1),
                 "recut_mm": round(p.recut_length, 1),
                 "saved_offcut_cm2": round(sum(g.area for g in s.waste.saved) / 100, 1) if s.waste else "",
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
         min_width: float = 20.0, min_area: float = 50.0, detour: float = 1.5, log=print) -> list[dict]:
    doc = ExportFile(export)
    for sheet in sorted(doc.sheets.values(), key=lambda s: s.page):
        sheet.plan(router, share_tol, stay_down, min_width, min_area, detour)
        log(f"page {sheet.page:02d} {sheet.material:<7} " + " | ".join(
            f"{p.kind} {p.source_travel:.0f}->{p.travel:.0f} mm" for p in sheet.passes))
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.write(output)
    return doc.report(table)
