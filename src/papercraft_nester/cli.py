from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from .converter import load_material_pages,load_pieces
from .nesting import NestingError,load_inventory,nest,source_layout
from .report import summary
from .svg import write_master

def build_parser():
    parser=argparse.ArgumentParser(prog="papercraft-nester",description="Nest labeled papercraft pieces onto finite cardstock inventory.")
    sub=parser.add_subparsers(dest="command",required=True)
    cmd=sub.add_parser("nest",help="nest SVG pieces and write one project-wide SVG master")
    cmd.add_argument("--svg",type=Path,required=True,help="converter SVG file")
    cmd.add_argument("--manifest",type=Path,required=True,help="converter YAML manifest")
    cmd.add_argument("--inventory",type=Path,required=True,help="finite sheet inventory JSON")
    cmd.add_argument("--output",type=Path,required=True,help="output master SVG path")
    cmd.add_argument("--gap-mm",type=float,help="override the inventory minimum piece gap")
    cmd.add_argument("--rotation-step",type=float,help="override angular search resolution in degrees")
    cmd.add_argument("--source-baseline",action="store_true",help="keep the source PDF sheet placement as a comparison baseline")
    return parser

def main(argv=None):
    args=build_parser().parse_args(argv)
    try:
        pieces,source_colors=load_pieces(args.svg,args.manifest)
        page_map=load_material_pages(args.manifest)
        stocks,gap,step=load_inventory(args.inventory)
        inventory=json.loads(args.inventory.read_text(encoding="utf-8"))
        gap=args.gap_mm if args.gap_mm is not None else gap
        step=args.rotation_step if args.rotation_step is not None else step
        if gap<0 or step<=0:raise ValueError("gap must be nonnegative and rotation step must be positive")
        colors={**source_colors,**inventory.get("material_colors",{})}
        for stock in stocks:stock.color=colors.get(stock.material,stock.color)
        if args.source_baseline:
            sheets=source_layout(pieces,stocks,gap)
            print("Source PDF placement selected as the comparison baseline.")
        else:
            try:sheets=nest(pieces,stocks,gap,step)
            except NestingError as search_error:
                sheets=source_layout(pieces,stocks,gap)
                print(f"Packing heuristic could not fit this inventory: {search_error}")
                print("Using the source PDF page arrangement as a valid comparison baseline.")
        args.output.parent.mkdir(parents=True,exist_ok=True)
        write_master(sheets,args.output,colors)
        print(summary(pieces,sheets,page_map))
        print(f"Minimum gap: {gap:g} mm | rotation search step: {step:g} degrees")
        print(f"Master SVG: {args.output.resolve()}")
    except (OSError,ValueError,NestingError,KeyError,json.JSONDecodeError) as exc:
        print(f"papercraft-nester: error: {exc}",file=sys.stderr)
        return 2
    return 0

if __name__=="__main__":raise SystemExit(main())
