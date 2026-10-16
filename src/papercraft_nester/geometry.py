from __future__ import annotations
import math
from shapely.geometry import Polygon as Shape
from .model import Point, Polygon

EPS=1e-7
def rotate_normalized(poly: Polygon,degrees: float):
    angle=math.radians(degrees);c,s=math.cos(angle),math.sin(angle);rotated=[(x*c-y*s,x*s+y*c) for x,y in poly]
    min_x=min(x for x,_ in rotated);min_y=min(y for _,y in rotated);max_x=max(x for x,_ in rotated);max_y=max(y for _,y in rotated)
    return [(x-min_x,y-min_y) for x,y in rotated],(min_x,min_y,max_x,max_y)
def translate(poly: Polygon,x: float,y: float)->Polygon:return [(px+x,py+y) for px,py in poly]
def bounds(poly: Polygon):return min(x for x,_ in poly),min(y for _,y in poly),max(x for x,_ in poly),max(y for _,y in poly)
def polygon_distance(a: Polygon,b: Polygon)->float:return Shape(a).distance(Shape(b))
def polygons_overlap(a: Polygon,b: Polygon)->bool:return Shape(a).intersection(Shape(b)).area>EPS
def candidate_angles(poly: Polygon,step_degrees: float)->list[float]:
    step=max(0.25,min(90.0,step_degrees));return [round(i*step,6) for i in range(max(1,math.ceil(360/step))) if i*step<360-EPS]
