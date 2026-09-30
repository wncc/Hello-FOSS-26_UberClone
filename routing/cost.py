"""Cost = Distance / (Speed x Priority)  (+ optional GraphHopper distance_influence)."""
import math

from .models import EdgeEvaluation


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
