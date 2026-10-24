"""Tool-path ordering on one sheet: a generalised TSP over jobs.

A job is something the tool does without moving to another job (cut one piece outline, score one
fold line, write one label). Each job has options (start vertex on a closed outline, or direction
of a fold line), each with an entry and an exit point. A route picks one option per job and an
order; its cost is the lifted travel from the sheet's home corner through every exit -> entry move.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field

Point = tuple[float, float]


def dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


@dataclass
class Job:
    name: str
    options: list[list[list[Point]]]  # option -> polylines in tool order
    reverse: list[int] = field(default_factory=list)  # option drawn backwards (same entry/exit swapped)

    @classmethod
    def loop(cls, name: str, ring: list[Point]):
        """Closed outline: one option per start vertex, each a closed polyline back to its start."""
        n = len(ring)
        return cls(name, [[ring[k:] + ring[:k] + [ring[k]]] for k in range(n)], list(range(n)))

    @classmethod
    def line(cls, name: str, a: Point, b: Point):
        return cls(name, [[[a, b]], [[b, a]]], [1, 0])

    @classmethod
    def strokes(cls, name: str, strokes: list[list[Point]]):
        """Pen strokes drawn in their order, or all backwards."""
        return cls(name, [strokes, [line[::-1] for line in reversed(strokes)]], [1, 0])

    def entry(self, k: int) -> Point:
        return self.options[k][0][0]

    def exit(self, k: int) -> Point:
        return self.options[k][-1][-1]


Route = list[tuple[int, int]]  # (job index, option index) in tool order


def travel(jobs: list[Job], route: Route, home: Point) -> float:
    pos, total = home, 0.0
    for j, k in route:
        total += dist(pos, jobs[j].entry(k))
        pos = jobs[j].exit(k)
    return total


class HeuristicRouter:
    """Nearest neighbour, then 2-opt on the job order and a DP over options, until no gain."""
    name = "heuristic"

    def solve(self, jobs: list[Job], home: Point) -> Route:
        if not jobs:
            return []
        route = self.nearest(jobs, home)
        best = travel(jobs, route, home)
        for _ in range(10):
            route = self.best_options(jobs, self.two_opt(jobs, route, home), home)
            cost = travel(jobs, route, home)
            if cost >= best - 1e-9:
                break
            best = cost
        return route

    @staticmethod
    def nearest(jobs, home):
        left, pos, route = set(range(len(jobs))), home, []
        while left:
            d, j, k = min((dist(pos, jobs[j].entry(k)), j, k) for j in left for k in range(len(jobs[j].options)))
            route.append((j, k))
            left.remove(j)
            pos = jobs[j].exit(k)
        return route

    @staticmethod
    def two_opt(jobs, route, home):
        """Reverse a stretch of jobs (each drawn backwards) when that shortens the travel."""
        route, n, improved = list(route), len(route), True
        while improved:
            improved = False
            for i in range(n - 1):
                before = jobs[route[i - 1][0]].exit(route[i - 1][1]) if i else home
                for k in range(i + 1, n):
                    first, last = route[i], route[k]
                    old = dist(before, jobs[first[0]].entry(first[1]))
                    new = dist(before, jobs[last[0]].exit(last[1]))
                    if k + 1 < n:
                        after = jobs[route[k + 1][0]].entry(route[k + 1][1])
                        old += dist(jobs[last[0]].exit(last[1]), after)
                        new += dist(jobs[first[0]].entry(first[1]), after)
                    if new < old - 1e-9:
                        route[i:k + 1] = [(j, jobs[j].reverse[o]) for j, o in reversed(route[i:k + 1])]
                        improved = True
        return route

    @staticmethod
    def best_options(jobs, route, home):
        """Exact choice of option per job for a fixed job order (layered shortest path)."""
        cost = [dist(home, jobs[route[0][0]].entry(k)) for k in range(len(jobs[route[0][0]].options))]
        back = []
        for (pj, _), (j, _) in zip(route, route[1:]):
            prev, row, arg = jobs[pj], [], []
            for k in range(len(jobs[j].options)):
                e = jobs[j].entry(k)
                c, p = min((cost[p] + dist(prev.exit(p), e), p) for p in range(len(prev.options)))
                row.append(c)
                arg.append(p)
            cost, back = row, back + [arg]
        k = min(range(len(cost)), key=cost.__getitem__)
        picks = [k]
        for arg in reversed(back):
            k = arg[k]
            picks.append(k)
        return [(j, k) for (j, _), k in zip(route, reversed(picks))]


class GurobiRouter(HeuristicRouter):
    """Exact GTSP over a capped set of options per job, warm-started from the heuristic.

    Lazy subtour cuts on job sets; the path starts at the home corner and may end anywhere.
    The order Gurobi finds is polished with the full option DP, and never returned if worse.
    """
    name = "gurobi"
    small = 2000  # variables allowed by the size-limited licence

    def __init__(self, time_limit: float = 30.0, max_options: int = 8, verbose: bool = False):
        import gurobipy  # noqa: F401  (fail early so the caller can fall back)
        self.time_limit, self.max_options, self.verbose = time_limit, max_options, verbose

    def candidates(self, jobs, j, chosen, max_options=None):
        """Options whose entry lies closest to another job, plus the heuristic's choice."""
        n, cap = len(jobs[j].options), max_options or self.max_options
        if n <= cap:
            return list(range(n))
        others = [jobs[i].entry(k) for i in range(len(jobs)) if i != j for k in range(len(jobs[i].options))]
        near = sorted(range(n), key=lambda k: min((dist(jobs[j].entry(k), p) for p in others), default=0))
        return sorted(set(near[:cap - 1]) | {chosen})

    def solve(self, jobs, home):
        import gurobipy as gp
        start = super().solve(jobs, home)
        if len(jobs) < 3:
            return start
        try:
            return self.exact(jobs, home, start)
        except gp.GurobiError as exc:  # e.g. the pip size-limited licence (2000 variables)
            if len(jobs) * (len(jobs) + 1) > self.small:
                print(f"gurobi: {exc}; keeping the heuristic route ({len(jobs)} jobs)")
                return start
        try:  # order only: one option per job (the heuristic's), the option DP picks the rest
            return self.exact(jobs, home, start, max_options=1)
        except gp.GurobiError as exc:
            print(f"gurobi: {exc}; keeping the heuristic route ({len(jobs)} jobs)")
            return start

    def exact(self, jobs, home, start, max_options=None):
        import gurobipy as gp
        chosen = dict(start)
        nodes = [(j, k) for j in range(len(jobs)) for k in self.candidates(jobs, j, chosen[j], max_options)]
        HOME = -1
        m = gp.Model()
        m.Params.OutputFlag = int(self.verbose)
        m.Params.TimeLimit = self.time_limit
        m.Params.LazyConstraints = 1
        arcs = {}
        for u, (ju, ku) in enumerate(nodes):
            arcs[HOME, u] = m.addVar(vtype="B", obj=dist(home, jobs[ju].entry(ku)))
            arcs[u, HOME] = m.addVar(vtype="B", obj=0.0)
            for v, (jv, kv) in enumerate(nodes):
                if jv != ju:
                    arcs[u, v] = m.addVar(vtype="B", obj=dist(jobs[ju].exit(ku), jobs[jv].entry(kv)))
        out = {u: [] for u in [HOME, *range(len(nodes))]}
        inn = {u: [] for u in out}
        for (u, v), x in arcs.items():
            out[u].append(x)
            inn[v].append(x)
        use = [gp.quicksum(inn[u]) for u in range(len(nodes))]
        for u in range(len(nodes)):
            m.addConstr(gp.quicksum(out[u]) == use[u])
        m.addConstr(gp.quicksum(out[HOME]) == 1)
        m.addConstr(gp.quicksum(inn[HOME]) == 1)
        for j in range(len(jobs)):
            m.addConstr(gp.quicksum(use[u] for u, (ju, _) in enumerate(nodes) if ju == j) == 1)
        index = {node: u for u, node in enumerate(nodes)}
        prev = HOME
        for node in start:
            arcs[prev, index[node]].Start = 1
            prev = index[node]
        arcs[prev, HOME].Start = 1

        def cut_subtours(model, where):
            if where != gp.GRB.Callback.MIPSOL:
                return
            val = model.cbGetSolution(list(arcs.values()))
            succ = {u: v for (u, v), x in zip(arcs, val) if x > 0.5}
            seen, u = set(), succ[HOME]
            while u != HOME:
                seen.add(u)
                u = succ[u]
            for s in [u for u in succ if u != HOME and u not in seen]:
                if s in seen:
                    continue
                cycle, u = [], s
                while u not in seen:
                    seen.add(u)
                    cycle.append(u)
                    u = succ[u]
                group = {nodes[u][0] for u in cycle}
                inside = [u for u, (j, _) in enumerate(nodes) if j in group]
                model.cbLazy(gp.quicksum(arcs[u, v] for u in inside for v in inside if (u, v) in arcs)
                             <= len(group) - 1)

        m.optimize(cut_subtours)
        if m.SolCount == 0:
            return start
        succ = {u: v for (u, v), x in arcs.items() if x.X > 0.5}
        route, u = [], succ[HOME]
        while u != HOME:
            route.append(nodes[u])
            u = succ[u]
        route = self.best_options(jobs, route, home)
        return route if travel(jobs, route, home) < travel(jobs, start, home) else start


def make_router(solver: str = "auto", time_limit: float = 30.0):
    if solver in ("auto", "gurobi"):
        try:
            return GurobiRouter(time_limit)
        except ImportError:
            if solver == "gurobi":
                raise
    return HeuristicRouter()
