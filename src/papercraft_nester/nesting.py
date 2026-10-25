from __future__ import annotations
import json
import re
from pathlib import Path
from .geometry import bounds,candidate_angles,polygon_distance,polygons_overlap,rotate_normalized,translate
from .model import Piece,Placement,Sheet,SheetStock

class NestingError(RuntimeError): pass

def load_inventory(path: Path):
    data=json.loads(path.read_text(encoding="utf-8"))
    gap=float(data.get("minimum_gap_mm",0.2));step=float(data.get("rotation_step_degrees",5.0))
    if gap<0 or step<=0: raise ValueError("minimum gap must be nonnegative and rotation step must be positive")
    stocks=[]
    for row in data.get("sheets",[]):
        material=str(row["material"])
        stock=SheetStock(material,float(row["width_mm"]),float(row["height_mm"]),int(row["quantity"]),data.get("material_colors",{}).get(material,"#777777"),str(row.get("label",f'{row["width_mm"]}x{row["height_mm"]} mm')))
        if stock.width_mm<=0 or stock.height_mm<=0 or stock.quantity<0: raise ValueError("sheet dimensions must be positive and quantity nonnegative")
        stocks.append(stock)
    if not stocks: raise ValueError("inventory has no sheet stock")
    return stocks,gap,step

def _candidate_positions(sheet:Sheet,piece:Piece,width:float,height:float,gap:float,angle:float):
    positions={(0.0,0.0)}
    for placed in sheet.placements:
        x0,y0,x1,y1=bounds(placed.polygon)
        positions.update(((x1+gap,y0),(x1+gap,y1-height),(x0-width-gap,y0),(x0-width-gap,y1-height),(x0,y1+gap),(x1-width,y1+gap),(x0,y0-height-gap),(x1-width,y0-height-gap)))
    source_min_x,source_min_y,_,_=bounds(piece.polygon);source_position=(source_min_x,source_min_y)
    if abs(angle%360)<1e-6 and (not sheet.placements or sheet.source_page==piece.source_page): positions.add(source_position)
    ordered=sorted(((x,y) for x,y in positions if x>=-1e-6 and y>=-1e-6 and x+width<=sheet.stock.width_mm+1e-6 and y+height<=sheet.stock.height_mm+1e-6),key=lambda p:(p[1],p[0]))
    if abs(angle%360)<1e-6 and (not sheet.placements or sheet.source_page==piece.source_page) and source_position in ordered:
        ordered.remove(source_position);ordered.insert(0,source_position)
    return ordered

def _find_on_sheet(piece:Piece,sheet:Sheet,gap:float,step:float):
    sx0,sy0,sx1,sy1=bounds(piece.polygon)
    same_source=not sheet.placements or sheet.source_page==piece.source_page
    if same_source and sx0>=-1e-6 and sy0>=-1e-6 and sx1<=sheet.stock.width_mm+1e-6 and sy1<=sheet.stock.height_mm+1e-6:
        valid=True
        for other in sheet.placements:
            distance=polygon_distance(piece.polygon,other.polygon)
            if (gap<=1e-7 and polygons_overlap(piece.polygon,other.polygon)) or (gap>1e-7 and distance<gap-1e-6):
                valid=False;break
        if valid:
            _,local=rotate_normalized(piece.polygon,0)
            return Placement(piece,sheet.index,sx0,sy0,0,piece.polygon,local)
    best=None;best_score=None
    for angle in candidate_angles(piece.polygon,step):
        normalized,local=rotate_normalized(piece.polygon,angle);min_x,min_y,max_x,max_y=local;w,h=max_x-min_x,max_y-min_y
        if w>sheet.stock.width_mm+1e-6 or h>sheet.stock.height_mm+1e-6: continue
        for x,y in _candidate_positions(sheet,piece,w,h,gap,angle):
            candidate=translate(normalized,x,y);valid=True
            for other in sheet.placements:
                ax0,ay0,ax1,ay1=bounds(candidate);bx0,by0,bx1,by1=bounds(other.polygon)
                bbox_gap=((max(ax0-bx1,bx0-ax1,0.0))**2+(max(ay0-by1,by0-ay1,0.0))**2)**0.5
                if bbox_gap>=gap-1e-7 and bbox_gap>0: continue
                if gap<=1e-7:
                    if polygons_overlap(candidate,other.polygon): valid=False;break
                elif polygon_distance(candidate,other.polygon)<gap-1e-6: valid=False;break
            if valid:
                score=(y+h,y,x,angle)
                if best_score is None or score<best_score: best_score=score;best=Placement(piece,sheet.index,x,y,angle,candidate,local)
                break
    return best

def nest(pieces:list[Piece],stocks:list[SheetStock],gap:float,step:float):
    by_material={}
    for stock in stocks: by_material.setdefault(stock.material,[]).append(stock)
    colours={}
    for piece in pieces: colours.setdefault(piece.source_page,set()).add(piece.material)
    result=[]
    for material in dict.fromkeys(p.material for p in pieces):
        # Single-colour source pages first, so they keep their PDF layout; pieces from mixed pages fill in after.
        items=sorted((p for p in pieces if p.material==material),key=lambda p:(len(colours[p.source_page])>1,p.source_page,-p.area_mm2,p.id))
        available=by_material.get(material,[]);slots=[s for s in available for _ in range(s.quantity)]
        if not slots: raise NestingError(f"inventory has no sheets for material {material}")
        opened=[]
        for piece in items:
            options=[]
            for sheet in opened:
                placement=_find_on_sheet(piece,sheet,gap,step if sheet.source_page==piece.source_page else max(step,15.0))
                if placement:
                    x0,y0,x1,y1=bounds(placement.polygon);options.append(((y1,y0,x0,sheet.stock.width_mm*sheet.stock.height_mm),sheet,placement))
            if options:
                _,sheet,placement=min(options,key=lambda r:r[0]);sheet.placements.append(placement);continue
            possible=[];seen=set()
            for slot,stock in enumerate(slots):
                key=(stock.material,stock.width_mm,stock.height_mm,stock.label)
                if key in seen: continue
                seen.add(key);probe=Sheet(stock,len(result)+len(opened)+1,piece.source_page)
                placement=_find_on_sheet(piece,probe,gap,step)
                if placement: possible.append(((stock.width_mm*stock.height_mm,stock.width_mm,stock.height_mm),slot,stock,placement))
            if not possible:
                dims=", ".join(f"{s.width_mm:g}x{s.height_mm:g} mm x{s.quantity}" for s in available)
                raise NestingError(f"piece {piece.id} ({piece.material}) does not fit remaining inventory: {dims}")
            _,slot,stock,placement=min(possible,key=lambda r:r[0]);slots.pop(slot)
            sheet=Sheet(stock,len(result)+len(opened)+1,piece.source_page);placement.sheet_index=sheet.index;sheet.placements.append(placement);opened.append(sheet)
        result.extend(opened)
    for index,sheet in enumerate(result,1):
        sheet.index=index
        for placement in sheet.placements: placement.sheet_index=index
    return result

def source_layout(pieces:list[Piece],stocks:list[SheetStock],gap:float):
    available=[stock for stock in stocks for _ in range(stock.quantity)];by_page={}
    for piece in pieces: by_page.setdefault(piece.source_page,[]).append(piece)
    sheets=[]
    for page,items in sorted(by_page.items()):
        material=items[0].material;candidates=[(i,s) for i,s in enumerate(available) if s.material==material and s.width_mm>=215.9 and s.height_mm>=279.4]
        if not candidates: raise NestingError(f"source-layout fallback needs a Letter-or-larger sheet for {material} page {page:02d}")
        slot,stock=min(candidates,key=lambda pair:pair[1].width_mm*pair[1].height_mm);available.pop(slot);sheet=Sheet(stock,len(sheets)+1,page)
        for piece in items:
            x0,y0,x1,y1=bounds(piece.polygon)
            if x0 < -1e-6 or y0 < -1e-6 or x1>stock.width_mm+1e-6 or y1>stock.height_mm+1e-6: raise NestingError(f"{piece.id} is outside the source Letter page")
            sheet.placements.append(Placement(piece,sheet.index,0,0,0,piece.polygon,(0,0,0,0)))
        for i,one in enumerate(sheet.placements):
            for two in sheet.placements[i+1:]:
                distance=polygon_distance(one.polygon,two.polygon)
                if gap<=1e-7 and polygons_overlap(one.polygon,two.polygon): raise NestingError(f"source pieces {one.piece.id} and {two.piece.id} overlap")
                if gap>1e-7 and distance<gap-1e-6: raise NestingError(f"source pieces {one.piece.id} and {two.piece.id} are only {distance:.3f} mm apart; fallback cannot honor {gap:g} mm gap")
        sheets.append(sheet)
    return sheets
