from __future__ import annotations
from dataclasses import dataclass,field
from typing import Any
import re
Point=tuple[float,float]
Polygon=list[Point]
@dataclass
class Piece:
    id:str
    material:str
    polygon:Polygon
    element:Any
    area_mm2:float
    source_offset:Point=(0.0,0.0)
    @property
    def source_page(self)->int:
        match=re.match(r"piece-(\d+)-",self.id)
        return int(match.group(1)) if match else 0
@dataclass
class SheetStock:
    material:str
    width_mm:float
    height_mm:float
    quantity:int
    color:str="#777777"
    label:str="stock"
@dataclass
class Placement:
    piece:Piece
    sheet_index:int
    x_mm:float
    y_mm:float
    angle_degrees:float
    polygon:Polygon
    local_bounds:tuple[float,float,float,float]
@dataclass
class Sheet:
    stock:SheetStock
    index:int
    source_page:int|None=None
    placements:list[Placement]=field(default_factory=list)
    @property
    def utilization(self)->float:
        return sum(p.piece.area_mm2 for p in self.placements)/(self.stock.width_mm*self.stock.height_mm)
