from __future__ import annotations
import json
import re
from pathlib import Path
import numpy as np
import shapely
from shapely.geometry import Polygon as Shape
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

RES=1.0  # mm per raster cell in the placement search

def _mask(shape,cols:int,rows:int):
    """Raster cells (row, col) whose square touches the shape."""
    xs,ys=np.meshgrid((np.arange(cols)+0.5)*RES,(np.arange(rows)+0.5)*RES)
    return shapely.contains_xy(shape.buffer(RES*0.75),xs,ys)

def _snug(piece:Piece,sheet:Sheet,gap:float,step:float):
    """Place the piece where it adds least to the sheet's used region seen from the top edge (its skyline),
    so pieces tuck into each other's curves and the clean offcut below stays as big as possible.
    Every angle and every raster position is tried; collisions come from an FFT correlation of the raster masks."""
    W,H=sheet.stock.width_mm,sheet.stock.height_mm;cols,rows=int(W/RES),int(H/RES)
    occupied=np.zeros((rows,cols),bool)
    for other in sheet.placements: occupied|=_mask(Shape(other.polygon).buffer(gap),cols,rows)
    filled=occupied.any(axis=0);skyline=np.r_[np.where(filled,rows-np.argmax(occupied[::-1],axis=0),0),np.zeros(cols,int)]
    spectrum=np.fft.rfft2(occupied.astype(float),s=(2*rows,2*cols));options=[]
    for angle in candidate_angles(piece.polygon,step):
        normalized,local=rotate_normalized(piece.polygon,angle);w,h=local[2]-local[0],local[3]-local[1]
        if w>W+1e-6 or h>H+1e-6: continue
        mask=_mask(Shape(normalized),int(np.ceil(w/RES))+1,int(np.ceil(h/RES))+1);mh,mw=mask.shape
        hits=np.fft.irfft2(spectrum*np.conj(np.fft.rfft2(mask.astype(float),s=(2*rows,2*cols))),s=(2*rows,2*cols))
        ny,nx=int((H-h)/RES)+1,int((W-w)/RES)+1;free=hits[:ny,:nx]<0.5
        used=mask.any(axis=0);bottom=np.where(used,mh-np.argmax(mask[::-1],axis=0),0)[used]
        for x in range(nx):
            ys=np.flatnonzero(free[:,x])
            if not len(ys): continue
            cost=np.maximum(0,ys[:,None]+bottom[None,:]-skyline[x:x+mw][used][None,:]).sum(axis=1)
            k=int(np.lexsort((ys,cost))[0]);options.append((int(cost[k]),int(ys[k])+mh,x,angle,normalized,local,int(ys[k])))
    for cost,_,x,angle,normalized,local,y in sorted(options,key=lambda o:o[:4])[:50]:
        candidate=translate(normalized,x*RES,y*RES)
        if all(polygon_distance(candidate,other.polygon)>=gap-1e-6 and not polygons_overlap(candidate,other.polygon) for other in sheet.placements):
            return Placement(piece,sheet.index,x*RES,y*RES,angle,candidate,local)
    return None

def _find_on_sheet(piece:Piece,sheet:Sheet,gap:float,step:float,keep_source:bool=True):
    sx0,sy0,sx1,sy1=bounds(piece.polygon)
    same_source=not sheet.placements or sheet.source_page==piece.source_page
    if keep_source and same_source and sx0>=-1e-6 and sy0>=-1e-6 and sx1<=sheet.stock.width_mm+1e-6 and sy1<=sheet.stock.height_mm+1e-6:
        valid=True
        for other in sheet.placements:
            distance=polygon_distance(piece.polygon,other.polygon)
            if (gap<=1e-7 and polygons_overlap(piece.polygon,other.polygon)) or (gap>1e-7 and distance<gap-1e-6):
                valid=False;break
        if valid:
            _,local=rotate_normalized(piece.polygon,0)
            return Placement(piece,sheet.index,sx0,sy0,0,piece.polygon,local)
    return _snug(piece,sheet,gap,step)

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
                placement=_find_on_sheet(piece,sheet,gap,step if sheet.source_page==piece.source_page else max(step,15.0),len(colours[piece.source_page])==1)
                if placement:
                    x0,y0,x1,y1=bounds(placement.polygon);options.append(((y1,y0,x0,sheet.stock.width_mm*sheet.stock.height_mm),sheet,placement))
            if options:
                _,sheet,placement=min(options,key=lambda r:r[0]);sheet.placements.append(placement);continue
            possible=[];seen=set()
            for slot,stock in enumerate(slots):
                key=(stock.material,stock.width_mm,stock.height_mm,stock.label)
                if key in seen: continue
                seen.add(key);probe=Sheet(stock,len(result)+len(opened)+1,piece.source_page)
                placement=_find_on_sheet(piece,probe,gap,step,len(colours[piece.source_page])==1)
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
