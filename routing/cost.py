"""Cost = Distance / (Speed x Priority)  (+ optional GraphHopper distance_influence)."""
import math
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable

from .models import EdgeEvaluation, EdgeMeta

if TYPE_CHECKING:
    from .turns import TurnModel


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


def route_time_breakdown(path: list[EdgeMeta], depart_at: datetime,
                         speed_fn: Callable[[EdgeMeta, datetime], float],
                         turns: "TurnModel | None" = None) -> tuple[float, float, float]:
    """(driving, point delays, turns) in seconds, advancing the clock along the route so a
    trip that runs into rush hour slows down mid-way. The final node's delay is not
    counted: the trip ends there without crossing it."""
    clock = depart_at
    driving = delays = turning = 0.0
    for i, edge in enumerate(path):
        if i and turns:
            turning += turns.cost_s(path[i - 1], edge)
        seconds = edge_time_s(edge.distance_m, speed_fn(edge, clock))
        if math.isinf(seconds) or math.isinf(turning):
            return math.inf, math.inf, math.inf
        driving += seconds
        if i < len(path) - 1:
            delays += edge.end_delay_s
        clock = depart_at + timedelta(seconds=driving + delays + turning)
    return driving, delays, turning


def route_eta_s(path: list[EdgeMeta], depart_at: datetime,
                speed_fn: Callable[[EdgeMeta, datetime], float], turns: "TurnModel | None" = None) -> float:
    return sum(route_time_breakdown(path, depart_at, speed_fn, turns))


def moving_speed_kmh(observed_kmh: float, edge: EdgeMeta) -> float:
    """Observed traversal speed with the expected wait at the end node removed, so a signal
    or toll booth is never learned as a slow road. Capped at the legal limit (or 3x expected)."""
    if edge.end_delay_s <= 0 or observed_kmh <= 0:
        return observed_kmh
    cap_kmh = edge.max_speed_kmh or 3 * edge.speed_kmh
    observed_s = edge.distance_m / (observed_kmh / 3.6)
    moving_s = max(observed_s - edge.end_delay_s, edge.distance_m / (cap_kmh / 3.6))
    return edge.distance_m / moving_s * 3.6
