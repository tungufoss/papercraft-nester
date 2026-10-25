from __future__ import annotations
import copy
import math
import re
import xml.etree.ElementTree as ET
from .converter import SVG_NS,INKSCAPE_NS,SODIPODI_NS
from .model import Sheet

NUM=r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"

def q(ns,tag):return f"{{{ns}}}{tag}"
def _ordered_nearest(sheet):
    remaining=list(sheet.placements)
    if not remaining:return []
    ordered=[remaining.pop(0)];current=ordered[0].polygon[0]
    while remaining:
        i=min(range(len(remaining)),key=lambda n:(remaining[n].polygon[0][0]-current[0])**2+(remaining[n].polygon[0][1]-current[1])**2)
        item=remaining.pop(i);ordered.append(item);current=item.polygon[0]
    return ordered
def placement_transform(placement):
    """(angle, tx, ty): the placed outline is rotate(angle) of the page-local outline, then moved by (tx, ty)."""
    min_x,min_y,_,_=placement.local_bounds
    return placement.angle_degrees,placement.x_mm-min_x,placement.y_mm-min_y
def _mover(angle,dx,dy):
    c,s=math.cos(math.radians(angle)),math.sin(math.radians(angle))
    return lambda x,y:(x*c-y*s+dx,x*s+y*c+dy)
def _move_path(d,move):
    values=[float(v) for v in re.findall(NUM,d)];out=[]
    for x,y in zip(values[::2],values[1::2]):nx,ny=move(x,y);out.append(f"{nx:.3f},{ny:.3f}")
    return "M "+" ".join(out)+(" Z" if d.rstrip().upper().endswith("Z") else "")
def write_export(sheets,output_path,source_root):
    """The nested sheets as a lowpoly-export/1 file (coordinates baked in, one Inkscape page per sheet), for `cutpath`."""
    if not sheets:raise ValueError("cannot export an empty nesting result")
    gap=20.0;per_row=10;xs,ys=[],[];x=y=row_h=0.0
    for index,sheet in enumerate(sheets):
        if index and index%per_row==0:x=0.0;y+=row_h+gap;row_h=0.0
        xs.append(x);ys.append(y);x+=sheet.stock.width_mm+gap;row_h=max(row_h,sheet.stock.height_mm)
    width=max(x+s.stock.width_mm for x,s in zip(xs,sheets));height=y+row_h
    attrs={k:v for k,v in source_root.attrib.items() if k.startswith("data-")}
    attrs.update({"width":f"{width/25.4:.4f}in","height":f"{height/25.4:.4f}in","viewBox":f"0 0 {width:.3f} {height:.3f}"})
    root=ET.Element(q(SVG_NS,"svg"),attrs)
    named=ET.SubElement(root,q(SODIPODI_NS,"namedview"),{q(INKSCAPE_NS,"document-units"):"mm"})
    layer=ET.SubElement(root,q(SVG_NS,"g"),{"id":"pieces",q(INKSCAPE_NS,"groupmode"):"layer",q(INKSCAPE_NS,"label"):"Pieces"})
    for index,(sheet,ox,oy) in enumerate(zip(sheets,xs,ys),1):
        ET.SubElement(named,q(INKSCAPE_NS,"page"),{"id":f"page-{index:02d}",q(INKSCAPE_NS,"label"):f"Sheet {index:02d} · {sheet.stock.material}","x":f"{ox:.3f}","y":f"{oy:.3f}","width":f"{sheet.stock.width_mm:.3f}","height":f"{sheet.stock.height_mm:.3f}"})
        for placement in sheet.placements:
            piece=copy.deepcopy(placement.piece.element);angle,tx,ty=placement_transform(placement);sx,sy=placement.piece.source_offset
            c,s=math.cos(math.radians(angle)),math.sin(math.radians(angle))
            move=_mover(angle,ox+tx-(sx*c-sy*s),oy+ty-(sx*s+sy*c))
            piece.set("data-source-page",str(index));piece.set("data-page-origin-mm",f"{ox:.3f} {oy:.3f}");piece.set("data-sheet",f"{index:02d}")
            for node in piece.iter():
                if node.tag==q(SVG_NS,"path") and node.get("d"):node.set("d",_move_path(node.get("d"),move))
                elif node.tag==q(SVG_NS,"text"):
                    nx,ny=move(float(node.get("x")),float(node.get("y")));node.set("x",f"{nx:.3f}");node.set("y",f"{ny:.3f}")
                    rot=re.search(rf"rotate\(\s*({NUM})",node.get("transform",""));turn=(float(rot.group(1)) if rot else 0.0)+angle
                    node.set("transform",f"rotate({turn:.1f} {nx:.3f} {ny:.3f})")
            layer.append(piece)
    ET.ElementTree(root).write(output_path,encoding="utf-8",xml_declaration=True)
def write_master(sheets,output_path,material_colors):
    if not sheets:raise ValueError("cannot export an empty nesting result")
    page_gap=15.0;width=max(s.stock.width_mm for s in sheets);height=sum(s.stock.height_mm for s in sheets)+page_gap*(len(sheets)-1)
    root=ET.Element(q(SVG_NS,"svg"),{"width":f"{width:.3f}mm","height":f"{height:.3f}mm","viewBox":f"0 0 {width:.3f} {height:.3f}"})
    ET.SubElement(root,q(SVG_NS,"title")).text="Papercraft nested cardstock master"
    named=ET.SubElement(root,q(SODIPODI_NS,"namedview"),{q(INKSCAPE_NS,"document-units"):"mm"});y_page=0.0
    for index,sheet in enumerate(sheets,1):
        label=f"Sheet {index:02d} - {sheet.stock.material} - {sheet.stock.label}"
        ET.SubElement(named,q(INKSCAPE_NS,"page"),{"id":f"page-{index:02d}",q(INKSCAPE_NS,"label"):label,"x":"0","y":f"{y_page:.3f}","width":f"{sheet.stock.width_mm:.3f}","height":f"{sheet.stock.height_mm:.3f}"})
        layer=ET.SubElement(root,q(SVG_NS,"g"),{"id":f"sheet-{index:02d}",q(INKSCAPE_NS,"groupmode"):"layer",q(INKSCAPE_NS,"label"):label,"data-material":sheet.stock.material,"data-stock-size":sheet.stock.label})
        for placement in _ordered_nearest(sheet):
            piece=copy.deepcopy(placement.piece.element);angle,tx,ty=placement_transform(placement);sx,sy=placement.piece.source_offset
            transform=f"translate({tx:.4f},{y_page+ty:.4f}) rotate({angle:.4f}) translate({-sx:.4f},{-sy:.4f})"
            piece.set("transform",transform);piece.set("data-sheet",f"{index:02d}");piece.set("data-material",placement.piece.material)
            cut=next((node for node in piece.iter() if node.get("data-operation")=="cut"),None)
            path=next((node for node in cut.iter() if node.tag.endswith("path")),None) if cut is not None else None
            if path is not None:
                color=material_colors.get(placement.piece.material,sheet.stock.color);path.set("fill",color);path.set("fill-opacity","0.16");path.set("stroke",color);path.set("data-material-color",color)
            layer.append(piece)
        y_page+=sheet.stock.height_mm+page_gap
    ET.ElementTree(root).write(output_path,encoding="utf-8",xml_declaration=True)
