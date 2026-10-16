from __future__ import annotations
import copy
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from .model import Piece

SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
SODIPODI_NS = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
ET.register_namespace("", SVG_NS)
ET.register_namespace("inkscape", INKSCAPE_NS)
ET.register_namespace("sodipodi", SODIPODI_NS)

def local_name(tag: str) -> str:return tag.rsplit("}",1)[-1]
def polygon_area(points):return abs(sum(points[i][0]*points[(i+1)%len(points)][1]-points[(i+1)%len(points)][0]*points[i][1] for i in range(len(points)))/2)
def parse_polygon_path(d: str):
    if not d.lstrip().upper().startswith("M") or not d.rstrip().upper().endswith("Z"):raise ValueError("cut outline must be one closed M...Z path")
    body=re.sub(r"[MmZz]"," ",d);values=[float(v) for v in re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?",body)]
    if len(values)<6 or len(values)%2:raise ValueError("cut outline has an invalid coordinate list")
    points=list(zip(values[::2],values[1::2]))
    if points[0]==points[-1]:points.pop()
    if len(points)<3:raise ValueError("cut outline needs at least three distinct vertices")
    return points

def load_material_pages(manifest_path: Path)->dict[int,str]:
    text=manifest_path.read_text(encoding="utf-8-sig");in_materials=False;current_id=None;result={}
    for line in text.splitlines():
        if re.match(r"^materials:\s*$",line):in_materials=True;continue
        if not in_materials:continue
        if line and not line[0].isspace() and not line.startswith("#"):break
        match=re.match(r"^\s*-\s+id:\s*([\w-]+)",line)
        if match:current_id=match.group(1);continue
        match=re.match(r"^\s*pages:\s*\[([^]]*)\]",line)
        if match and current_id:
            for page in re.findall(r"\d+",match.group(1)):result[int(page)]=current_id
    if not result:raise ValueError(f"no material page mapping found in {manifest_path}")
    return result

def _page_offsets(root)->dict[int,tuple[float,float]]:
    offsets={}
    for node in root.iter():
        if local_name(node.tag)!="page":continue
        match=re.search(r"(\d+)$",node.get("id", ""))
        if match:offsets[int(match.group(1))]=(float(node.get("x","0")),float(node.get("y","0")))
    return offsets

def load_pieces(svg_path: Path,manifest_path: Path):
    root=ET.parse(svg_path).getroot();material_pages=load_material_pages(manifest_path);page_offsets=_page_offsets(root)
    colors={};pieces=[]
    for element in root.iter():
        if local_name(element.tag)!="g" or not re.fullmatch(r"piece-\d+-\d+",element.get("id","")):continue
        match=re.match(r"piece-(\d+)-",element.get("id",""));page=int(match.group(1)) if match else 0
        material=element.get("data-material") or material_pages.get(page)
        if not material:continue
        offset=page_offsets.get(page,(0.0,0.0))
        cut=next((node for node in element.iter() if node.get("data-operation")=="cut"),None)
        path=next((node for node in cut.iter() if local_name(node.tag)=="path"),None) if cut is not None else None
        if path is None or not path.get("d"):raise ValueError(f"piece {element.get('id')} has no cut outline")
        polygon=[(x-offset[0],y-offset[1]) for x,y in parse_polygon_path(path.get("d",""))]
        area=polygon_area(polygon)
        if area<=0.01:raise ValueError(f"piece {element.get('id')} has a degenerate cut outline")
        colors.setdefault(material,{"red":"#d62828","green":"#27864b","yellow":"#f2cf32","black":"#222222"}.get(material,"#777777"))
        pieces.append(Piece(element.get("id",f"piece-{len(pieces)+1}"),material,polygon,copy.deepcopy(element),area,offset))
    if not pieces:raise ValueError(f"no piece groups found in {svg_path}")
    return pieces,colors
