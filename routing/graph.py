"""In-memory road graph used by the local router, tests, and offline replays."""
from __future__ import annotations

import math
from collections import defaultdict

from .models import EdgeMeta

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


class RoadGraph:
    def __init__(self, nodes: dict[str, tuple[float, float]], edges: list[EdgeMeta]):
        self.nodes = nodes
        self.edges: dict[str, EdgeMeta] = {}
        self.out: dict[str, list[EdgeMeta]] = defaultdict(list)
        for e in edges:
            if e.from_node not in nodes or e.to_node not in nodes:
                raise ValueError(f"edge {e.segment_id} references unknown node")
            self.edges[e.segment_id] = e
            self.out[e.from_node].append(e)
        self.max_speed_kmh = max((e.speed_kmh for e in edges), default=1.0)

    def nearest_node(self, point: tuple[float, float]) -> str:
        # Linear scan is fine for tests; production snapping belongs to GraphHopper or a KD-tree.
        return min(self.nodes, key=lambda n: haversine_m(self.nodes[n], point))
