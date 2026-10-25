"""Cost = Distance / (Speed x Priority)  (+ optional GraphHopper distance_influence)."""
import math
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable

from .models import EdgeEvaluation, EdgeMeta
from .delay_model import FittedDelayModel

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


def point_delay_s(
    edge: EdgeMeta,
    when: datetime,
    learned: FittedDelayModel | None = None,
) -> float:
    """Return learned signal wait or the existing mapped delay."""
    if learned is None or "traffic_signals" not in edge.end_features:
        return edge.end_delay_s

    return learned.signal_wait_s(
        edge.to_node,
        when,
        edge.end_delay_s,
    )


def route_time_breakdown(
    path: list[EdgeMeta],
    depart_at: datetime,
    speed_fn: Callable[[EdgeMeta, datetime], float],
    turns: "TurnModel | None" = None,
    learned: FittedDelayModel | None = None,
) -> tuple[float, float, float]:
    clock = depart_at
    driving = delays = turning = 0.0

    for i, edge in enumerate(path):
        if i and turns:
            cost = turns.cost_s(path[i - 1], edge, clock)
            if math.isinf(cost):
                return math.inf, math.inf, math.inf
            turning += cost
            clock += timedelta(seconds=cost)

        seconds = edge_time_s(edge.distance_m, speed_fn(edge, clock))
        if math.isinf(seconds):
            return math.inf, math.inf, math.inf

        driving += seconds
        clock += timedelta(seconds=seconds)

        if i < len(path) - 1:
            wait = point_delay_s(edge, clock, learned)
            delays += wait
            clock += timedelta(seconds=wait)

    return driving, delays, turning


def route_eta_s(path: list[EdgeMeta], depart_at: datetime,
                speed_fn: Callable[[EdgeMeta, datetime], float], turns: "TurnModel | None" = None) -> float:
    return sum(route_time_breakdown(path, depart_at, speed_fn, turns))


def moving_speed_kmh(observed_kmh: float, edge: EdgeMeta,
                     expected_wait_s: float | None = None) -> float:
    """Observed traversal speed with the expected wait at the end node removed, so a signal
    or toll booth is never learned as a slow road. Capped at the legal limit (or 3x expected).
    expected_wait_s: the wait to remove (e.g. a learned signal wait); defaults to the mapped one."""
    wait_s = edge.end_delay_s if expected_wait_s is None else expected_wait_s
    if wait_s <= 0 or observed_kmh <= 0:
        return observed_kmh
    cap_kmh = edge.max_speed_kmh or 3 * edge.speed_kmh
    observed_s = edge.distance_m / (observed_kmh / 3.6)
    moving_s = max(observed_s - wait_s, edge.distance_m / (cap_kmh / 3.6))
    return edge.distance_m / moving_s * 3.6
