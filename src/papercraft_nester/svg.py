from __future__ import annotations
import copy
import xml.etree.ElementTree as ET
from .converter import SVG_NS,INKSCAPE_NS,SODIPODI_NS
from .model import Sheet

def q(ns,tag):return f"{{{ns}}}{tag}"
def _ordered_nearest(sheet):
    remaining=list(sheet.placements)
    if not remaining:return []
    ordered=[remaining.pop(0)];current=ordered[0].polygon[0]
    while remaining:
        i=min(range(len(remaining)),key=lambda n:(remaining[n].polygon[0][0]-current[0])**2+(remaining[n].polygon[0][1]-current[1])**2)
        item=remaining.pop(i);ordered.append(item);current=item.polygon[0]
    return ordered
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
            piece=copy.deepcopy(placement.piece.element);min_x,min_y,_,_=placement.local_bounds;sx,sy=placement.piece.source_offset
            transform=f"translate({placement.x_mm:.4f},{y_page+placement.y_mm:.4f}) rotate({placement.angle_degrees:.4f}) translate({-min_x:.4f},{-min_y:.4f}) translate({-sx:.4f},{-sy:.4f})"
            piece.set("transform",transform);piece.set("data-sheet",f"{index:02d}");piece.set("data-material",placement.piece.material)
            cut=next((node for node in piece.iter() if node.get("data-operation")=="cut"),None)
            path=next((node for node in cut.iter() if node.tag.endswith("path")),None) if cut is not None else None
            if path is not None:
                color=material_colors.get(placement.piece.material,sheet.stock.color);path.set("fill",color);path.set("fill-opacity","0.16");path.set("stroke",color);path.set("data-material-color",color)
            layer.append(piece)
        y_page+=sheet.stock.height_mm+page_gap
    ET.ElementTree(root).write(output_path,encoding="utf-8",xml_declaration=True)
