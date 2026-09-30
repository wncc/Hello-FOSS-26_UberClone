"""Cost = Distance / (Speed x Priority)  (+ optional GraphHopper distance_influence)."""
import math
from datetime import datetime, timedelta
from typing import Callable, Iterable

from .models import EdgeEvaluation, EdgeMeta


def kmh_to_mps(kmh: float) -> float:
    return kmh / 3.6


def edge_cost(distance_m: float, speed_kmh: float, priority: float,
              distance_influence: float = 0.0) -> float:
    """Weighted seconds. Priority 0 or speed 0 means the edge is blocked."""
    if priority <= 0 or speed_kmh <= 0:
        return math.inf
    return distance_m / (kmh_to_mps(speed_kmh) * priority) + distance_influence * distance_m / 1000.0


def edge_time_s(distance_m: float, speed_kmh: float) -> float:
    return math.inf if speed_kmh <= 0 else distance_m / kmh_to_mps(speed_kmh)


def route_cost(legs: list[tuple[float, EdgeEvaluation]], distance_influence: float = 0.0) -> float:
    """legs: (distance_m, evaluation) pairs."""
    return sum(edge_cost(d, e.speed_kmh, e.priority, distance_influence) for d, e in legs)


def route_eta_s(path: Iterable[EdgeMeta], depart_at: datetime,
                speed_fn: Callable[[EdgeMeta, datetime], float]) -> float:
    """Walk the route advancing the clock, so a trip that runs into rush hour slows down mid-way."""
    clock = depart_at
    total = 0.0
    for edge in path:
        seconds = edge_time_s(edge.distance_m, speed_fn(edge, clock))
        if math.isinf(seconds):
            return math.inf
        total += seconds
        clock += timedelta(seconds=seconds)
    return total
