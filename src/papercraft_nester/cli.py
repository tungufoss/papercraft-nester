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
    cmd=sub.add_parser("cutpath",help="order cut, fold and pen paths per sheet without moving pieces")
    cmd.add_argument("--svg",type=Path,required=True,help="converter export SVG (lowpoly-export/1)")
    cmd.add_argument("--output",type=Path,required=True,help="output SVG with Cut, Fold valley, Fold mountain, Draw layers")
    cmd.add_argument("--table",type=Path,help="per-sheet CSV report (default: OUTPUT with .csv)")
    cmd.add_argument("--solver",choices=["auto","gurobi","heuristic"],default="auto",help="auto uses Gurobi when gurobipy is installed")
    cmd.add_argument("--time-limit",type=float,default=10.0,help="Gurobi seconds per pass and sheet")
    cmd.add_argument("--stay-down",type=float,nargs="?",const=10.0,default=0.0,metavar="STRIP",help="keep cutting (not folds) through waste paper: strips and notches narrower than STRIP mm between pieces (bare flag: 10); clean offcut is never cut (default: always lift)")
    cmd.add_argument("--min-width",type=float,default=10.0,help="with --stay-down: a saved offcut is at least this wide everywhere, mm")
    cmd.add_argument("--min-area",type=float,default=25.0,help="with --stay-down: smallest offcut to save, cm2")
    cmd.add_argument("--detour",type=float,default=1.5,help="with --stay-down: a blade-down path through waste may be this many times the straight move")
    cmd.add_argument("--share-tol",type=float,default=0.35,help="mm: a neighbour's edge this close is cut once")
    return parser

def cutpath(args):
    from .cutpath import plan
    from .route import make_router
    router=make_router(args.solver,args.time_limit)
    table=args.table or args.output.with_suffix(".csv")
    rows=plan(args.svg,args.output,table,router,args.share_tol,args.stay_down,args.min_width,args.min_area,args.detour)
    for kind in ("cut","valley","mountain","draw"):
        sel=[r for r in rows if r["pass"]==kind]
        print(f"{kind:<8} travel {sum(r['travel_source_mm'] for r in sel):.0f} -> {sum(r['travel_mm'] for r in sel):.0f} mm, length {sum(r['length_source_mm'] for r in sel):.0f} -> {sum(r['length_mm'] for r in sel):.0f} mm, {sum(r['lifts'] for r in sel)} lifts, {sum(r['waste_cut_mm'] for r in sel):.0f} mm cut through waste")
    print(f"Solver: {router.name} | plan SVG: {args.output.resolve()} | table: {table.resolve()}")
    return 0

def main(argv=None):
    args=build_parser().parse_args(argv)
    if args.command=="cutpath":
        try:return cutpath(args)
        except (OSError,ValueError) as exc:
            print(f"papercraft-nester: error: {exc}",file=sys.stderr);return 2
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
