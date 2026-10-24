"""Interactive cut-plan map (Leaflet): one sheet at a time, a layer per tool pass.

    PYTHONPATH=src python scripts/cutpath-viewer.py examples/example-export.svg img/cutpath-viewer.html [--stay-down] [--gurobi]

Every pass is drawn the same way in its own colour: the path, an arrow every few cm, a numbered
node where the tool goes down (0 = sheet corner) and the lifted moves. Fold lines also carry their
order at the midpoint. Writes one self-contained HTML file (Leaflet 1.9.4 inlined from scripts/vendor/leaflet, BSD-2).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from papercraft_nester.cutpath import ExportFile
from papercraft_nester.route import dist, make_router

VENDOR = Path(__file__).parent / "vendor" / "leaflet"
PASSES = {"cut": ("Cut", "#000000", ""), "valley": ("Fold valley", "#2e8b57", "6 4"),
          "mountain": ("Fold mountain", "#1f5fbf", "9 3 2 3"), "draw": ("Draw", "#c2255c", "")}


def r(p):
    return [round(p[0], 2), round(p[1], 2)]


def sheet_data(sheet) -> dict:
    out = {"page": sheet.page, "material": sheet.material, "origin": r(sheet.origin), "size": r(sheet.size),
           "pieces": [[r(p) for p in piece.rings[0]] for piece in sheet.pieces],
           "saved": [[r(p) for p in poly.exterior.coords] for poly in (sheet.waste.saved if sheet.waste else [])],
           "passes": {}}
    for p in sheet.passes:
        lifts, pos = [], sheet.origin
        for _, run in p.strokes:
            if dist(pos, run[0]) > 1e-6:
                lifts.append([r(pos), r(run[0])])
            pos = run[-1]
        out["passes"][p.kind] = {
            "strokes": [[r(q) for q in run] for _, run in p.strokes],
            "lines": [[r(line[0]), r(line[-1])] for job in p.lines for line in job] if p.kind in ("valley", "mountain") else [],
            "bridges": [[r(q) for q in b] for b in p.bridges], "lifts": lifts,
            "stats": {"lifts": len(p.strokes), "travel_mm": round(p.travel), "source_mm": round(p.source_travel)}}
    return out


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cut plan map</title>
<style>__LEAFLET_CSS__</style>
<script>__LEAFLET_JS__</script>
<style>
html,body{margin:0;height:100%;font-family:Arial,sans-serif;background:#fff}
#bar{padding:6px 10px;font-size:14px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
#map{position:absolute;top:40px;bottom:0;left:0;right:0;background:#f8f9fa}
.node{background:var(--c);color:#fff;border:1.5px solid #fff;border-radius:50%;width:18px;height:18px;
  font:bold 10px/18px Arial;text-align:center;margin:-9px 0 0 -9px}
.num{color:var(--c);font:bold 10px Arial;text-shadow:0 0 2px #fff,0 0 2px #fff;white-space:nowrap;margin:-6px 0 0 -6px}
</style></head><body>
<div id="bar"><label>Sheet <select id="sheet"></select></label><span id="stats"></span></div>
<div id="map"></div>
<script>
const DATA = __DATA__, PASSES = __PASSES__;
const map = L.map('map', {crs: L.CRS.Simple, minZoom: -2, maxZoom: 5, zoomSnap: 0.25});
const ll = p => [-p[1], p[0]];
let groups = {}, control = null;
function arrows(line, colour, every, group) {
  let next = every / 2, run = 0;
  for (let i = 1; i < line.length; i++) {
    const [x1, y1] = line[i - 1], [x2, y2] = line[i], len = Math.hypot(x2 - x1, y2 - y1);
    if (!len) continue;
    const ux = (x2 - x1) / len, uy = (y2 - y1) / len, s = 2.2;
    while (next <= run + len) {
      const t = next - run, cx = x1 + ux * t, cy = y1 + uy * t;
      L.polygon([[cx + ux * s, cy + uy * s], [cx - ux * s - uy * s * .6, cy - uy * s + ux * s * .6],
                 [cx - ux * s + uy * s * .6, cy - uy * s - ux * s * .6]].map(ll),
                {color: colour, weight: 0, fillOpacity: 1, interactive: false}).addTo(group);
      next += every;
    }
    run += len;
  }
}
function label(p, text, colour, cls, group) {
  L.marker(ll(p), {icon: L.divIcon({className: '', html: `<div class="${cls}" style="--c:${colour}">${text}</div>`,
    iconSize: null}), interactive: false}).addTo(group);
}
function show(i) {
  const s = DATA[i];
  Object.values(groups).forEach(g => map.removeLayer(g));
  if (control) control.remove();
  groups = {};
  const base = L.layerGroup();
  const [ox, oy] = s.origin, [w, h] = s.size;
  L.rectangle([ll([ox, oy]), ll([ox + w, oy + h])], {color: '#999', weight: 1, fill: false}).addTo(base);
  s.pieces.forEach(p => L.polygon(p.map(ll), {color: '#adb5bd', weight: 0.5, fillColor: '#e9ecef', fillOpacity: 1}).addTo(base));
  groups['Pieces'] = base;
  if (s.saved.length) {
    const g = L.layerGroup();
    s.saved.forEach(p => L.polygon(p.map(ll), {color: '#2b8a3e', weight: 1, fillColor: '#40c057', fillOpacity: .25}).addTo(g));
    groups['Saved offcut'] = g;
  }
  const stats = [];
  for (const [kind, [name, colour, dash]] of Object.entries(PASSES)) {
    const p = s.passes[kind], g = L.layerGroup();
    if (!p || !p.strokes.length) continue;
    p.strokes.forEach(run => {
      L.polyline(run.map(ll), {color: colour, weight: 1.6, dashArray: dash || null}).addTo(g);
      arrows(run, colour, kind === 'cut' ? 60 : 1e9, g);
    });
    p.lines.forEach((ln, n) => {
      const [[x1, y1], [x2, y2]] = ln, L2 = Math.hypot(x2 - x1, y2 - y1) || 1;
      arrows(ln, colour, L2 * 1.0001, g);
      label([(x1 + x2) / 2 - (y2 - y1) / L2 * 2.6, (y1 + y2) / 2 + (x2 - x1) / L2 * 2.6], n + 1, colour, 'num', g);
    });
    p.bridges.forEach(b => L.polyline(b.map(ll), {color: '#f76707', weight: 3}).addTo(g));
    p.lifts.forEach(m => {
      L.polyline(m.map(ll), {color: colour, weight: 1.2, dashArray: '1 5', opacity: .8}).addTo(g);
      arrows(m, colour, Math.hypot(m[1][0] - m[0][0], m[1][1] - m[0][1]) * 1.0001 || 1, g);
    });
    if (kind !== 'draw' && !p.lines.length) {
      label(s.origin, 0, colour, 'node', g);
      p.strokes.forEach((run, n) => label(run[0], n + 1, colour, 'node', g));
    }
    groups[name] = g;
    stats.push(`${name}: ${p.stats.lifts} lifts, travel ${(p.stats.source_mm / 1000).toFixed(2)} → ${(p.stats.travel_mm / 1000).toFixed(2)} m`);
  }
  Object.entries(groups).forEach(([k, g]) => { if (k !== 'Draw') g.addTo(map); });
  control = L.control.layers(null, groups, {collapsed: false}).addTo(map);
  document.getElementById('stats').textContent = `${s.material} · ` + stats.join(' · ');
  map.fitBounds([ll([ox, oy]), ll([ox + w, oy + h])], {padding: [10, 10]});
}
const sel = document.getElementById('sheet');
DATA.forEach((s, i) => sel.add(new Option(`Page ${String(s.page).padStart(2, '0')} · ${s.material}`, i)));
sel.onchange = () => show(+sel.value);
show(0);
</script></body></html>
"""


def main(src: Path, dst: Path, stay_down: float = 0.0, solver: str = "heuristic") -> None:
    doc, router = ExportFile(src), make_router(solver, 10.0)
    sheets = [sheet_data(s.plan(router, 0.35, stay_down)) for s in sorted(doc.sheets.values(), key=lambda s: (s.page, s.material))]
    page = PAGE.replace("__DATA__", json.dumps(sheets, separators=(",", ":"))).replace("__PASSES__", json.dumps(PASSES))
    page = page.replace("__LEAFLET_CSS__", (VENDOR / "leaflet.css").read_text(encoding="utf-8"))
    dst.write_text(page.replace("__LEAFLET_JS__", (VENDOR / "leaflet.js").read_text(encoding="utf-8")), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), 10.0 if "--stay-down" in sys.argv[3:] else 0.0,
         "gurobi" if "--gurobi" in sys.argv[3:] else "heuristic")
