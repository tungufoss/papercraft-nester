from __future__ import annotations
import math
from collections import defaultdict
from .geometry import bounds
from .model import Piece, Sheet

def _travel(points: list[tuple[float,float]]) -> float:
    if len(points)<2:return 0.0
    remaining=points[1:]; current=points[0]; distance=0.0
    while remaining:
        index=min(range(len(remaining)),key=lambda i:math.dist(current,remaining[i]))
        nxt=remaining.pop(index); distance+=math.dist(current,nxt); current=nxt
    return distance

def source_travel(pieces: list[Piece]) -> float:
    by_page=defaultdict(list)
    for piece in pieces:
        match=piece.id.split("-")
        by_page[match[1] if len(match)>2 else ""].append(piece.polygon[0])
    return sum(_travel(points) for points in by_page.values())

def packed_travel(sheets: list[Sheet]) -> float:
    total=0.0
    for sheet in sheets:
        points=[]
        for placement in sheet.placements:
            x0,y0,x1,y1=placement.local_bounds
            # polygon's first source vertex after normalization/rotation
            points.append(placement.polygon[0])
        total+=_travel(points)
    return total

def summary(pieces: list[Piece], sheets: list[Sheet], source_page_map: dict[int,str]) -> str:
    baseline=defaultdict(set)
    for page,material in source_page_map.items(): baseline[material].add(page)
    lines=["Bowser Letter nesting benchmark",f"Pieces: {len(pieces)} | baseline source sheets: {sum(map(len,baseline.values()))} | packed sheets: {len(sheets)}"]
    by_material=defaultdict(list)
    for sheet in sheets: by_material[sheet.stock.material].append(sheet)
    for material in sorted(set(p.material for p in pieces)):
        group=by_material[material]
        base=len(baseline.get(material,()))
        lines.append(f"{material}: {base} source -> {len(group)} packed; utilization by sheet: " + (", ".join(f"{s.utilization*100:.1f}%" for s in group) if group else "no sheets"))
    lines.append(f"Estimated inter-piece travel: source {source_travel(pieces):.1f} mm; packed {packed_travel(sheets):.1f} mm (nearest-neighbor order)")
    lines.append("Packing uses a deterministic heuristic; lower sheet count is a target, not a global-optimality guarantee.")
    return "\n".join(lines)
