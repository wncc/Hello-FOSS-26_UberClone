"""In-memory road graph used by the local router, tests, and offline replays."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable

from .models import EdgeMeta, RoadAccess
from .road_classes import RoadClass

EARTH_RADIUS_M = 6_371_000.0
SNAP_CELL_DEG = 0.005            # ~550 m grid cells for nearest-road lookups
DEFAULT_MAX_SNAP_M = 750.0       # farther than this from any usable road = outside the service area

# Riders and drivers are never placed on these: expressways and roads they may not use.
_UNSNAPPABLE_ACCESS = (RoadAccess.NO, RoadAccess.PRIVATE, RoadAccess.DELIVERY)


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


class _Grid:
    def __init__(self) -> None:
        self.cells: dict[tuple[int, int], list[str]] = defaultdict(list)

    @staticmethod
    def cell(p: tuple[float, float]) -> tuple[int, int]:
        return int(math.floor(p[0] / SNAP_CELL_DEG)), int(math.floor(p[1] / SNAP_CELL_DEG))

    def add(self, node: str, p: tuple[float, float]) -> None:
        self.cells[self.cell(p)].append(node)


class RoadGraph:
    def __init__(self, nodes: dict[str, tuple[float, float]], edges: list[EdgeMeta]):
        self.nodes = nodes
        self.edges: dict[str, EdgeMeta] = {}
        self.out: dict[str, list[EdgeMeta]] = defaultdict(list)
        self._starts, self._ends = _Grid(), _Grid()
        seen_start: set[str] = set()
        seen_end: set[str] = set()
        for e in edges:
            if e.from_node not in nodes or e.to_node not in nodes:
                raise ValueError(f"edge {e.segment_id} references unknown node")
            self.edges[e.segment_id] = e
            self.out[e.from_node].append(e)
            if e.road_class is RoadClass.MOTORWAY or e.road_access in _UNSNAPPABLE_ACCESS:
                continue
            if e.from_node not in seen_start:
                seen_start.add(e.from_node)
                self._starts.add(e.from_node, nodes[e.from_node])
            if e.to_node not in seen_end:
                seen_end.add(e.to_node)
                self._ends.add(e.to_node, nodes[e.to_node])
        self.max_speed_kmh = max((e.speed_kmh for e in edges), default=1.0)

    def nearest_node(self, point: tuple[float, float], role: str = "start",
                     max_m: float = DEFAULT_MAX_SNAP_M) -> str | None:
        """Nearest node you can depart from (`start`) or arrive at (`end`) on a usable road."""
        grid = self._starts if role == "start" else self._ends
        ci, cj = _Grid.cell(point)
        cell_m = SNAP_CELL_DEG * 111_000 * max(math.cos(math.radians(point[0])), 0.2)   # shorter (east-west) side
        reach = int(math.ceil(max_m / cell_m)) + 1
        best, best_d = None, max_m
        for ring in range(reach + 1):
            for i in range(ci - ring, ci + ring + 1):
                for j in range(cj - ring, cj + ring + 1):
                    if max(abs(i - ci), abs(j - cj)) != ring:
                        continue            # only the cells on this ring
                    for n in grid.cells.get((i, j), ()):
                        d = haversine_m(self.nodes[n], point)
                        if d < best_d:
                            best, best_d = n, d
            # Every node on the next ring is at least `ring` whole cells away from the point.
            if best is not None and ring * cell_m >= best_d:
                break
        return best


def graph_from_edges(edges: Iterable[EdgeMeta]) -> RoadGraph:
    """Build a RoadGraph using each edge's end-point geometry as node coordinates."""
    edges = list(edges)
    nodes: dict[str, tuple[float, float]] = {}
    for e in edges:
        if len(e.geometry) >= 2:
            nodes.setdefault(e.from_node, e.geometry[0])
            nodes.setdefault(e.to_node, e.geometry[-1])
    return RoadGraph(nodes, edges)
