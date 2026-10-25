"""Extract conservative junction-wait candidates from GPS trips.

What is measured
----------------
For every time a trip passes a junction, we measure how long the vehicle was
stopped just before / at it. A trip that passes a signal without stopping is
recorded as a 0-second wait, so the average is the expected delay per crossing
(the same meaning as the router's fixed default) and not "the wait, given that
you had to stop".

These are GPS-inferred candidates, not confirmed signal phases. A stop near a
junction can also be a queue spill-back, a pickup or a parked car. Stops longer
than ``max_wait_s`` are dropped as not junction waits.

Known limits: waits in queues longer than ``junction_radius_m`` are under-
measured, and a slow crawl is not counted as a stop. Both make the result lower
than the truth, never higher.
"""

from __future__ import annotations

from .delay_model import DelayKind, DelayObservation
from .graph import haversine_m
from .map_matching import GPSObservation, distance_to_segment_m
from .models import EdgeMeta

_BOX_MARGIN_DEG = 0.001      # ~110 m around the trip when choosing nearby roads
_REACH_M = 250.0             # a ping pair cannot pass a junction from further away
_MAX_REF_STEPS = 3           # how many pings to look back / forward for a clear leg
_EDGE_TOLERANCE_M = 10.0     # roads this much farther than the best one still compete
_AMBIGUITY_M = 3.0


def _edge_distance_m(location: tuple[float, float], edge: EdgeMeta) -> float:
    return min(
        distance_to_segment_m(location, a, b)
        for a, b in zip(edge.geometry, edge.geometry[1:])
    )


def _nearby_edges(
    points: list[GPSObservation], edges: dict[str, EdgeMeta]
) -> list[EdgeMeta]:
    """Keep only roads near the trip, so matching does not scan a whole city."""
    south = min(p.lat for p in points) - _BOX_MARGIN_DEG
    north = max(p.lat for p in points) + _BOX_MARGIN_DEG
    west = min(p.lng for p in points) - _BOX_MARGIN_DEG
    east = max(p.lng for p in points) + _BOX_MARGIN_DEG
    kept = []
    for edge in edges.values():
        if len(edge.geometry) < 2:
            continue
        lats = [g[0] for g in edge.geometry]
        lngs = [g[1] for g in edge.geometry]
        if max(lats) < south or min(lats) > north:
            continue
        if max(lngs) < west or min(lngs) > east:
            continue
        kept.append(edge)
    return kept


def _unique_edge(candidates, wanted) -> str | None:
    """The one road that satisfies ``wanted`` (e.g. 'ends at this junction').

    Direction comes from the road network: a road entering the junction must end
    there, a road leaving it must start there. This separates the two directions
    of a two-way road without needing a compass heading. If two roads fit about
    equally well, the match is rejected.
    """
    fits = sorted(
        (distance, edge.segment_id)
        for distance, edge in candidates
        if wanted(edge)
    )
    if not fits:
        return None
    if len(fits) > 1 and fits[1][0] - fits[0][0] < _AMBIGUITY_M:
        return None
    return fits[0][1]


def extract_delay_observations(
    observations: list[GPSObservation],
    edges: dict[str, EdgeMeta],
    driver_id: str,
    *,
    junction_radius_m: float = 50.0,
    stationary_radius_m: float = 10.0,
    leg_min_m: float = 15.0,
    pass_radius_m: float = 15.0,
    match_radius_m: float = 30.0,
    max_gap_s: float = 15.0,
    min_wait_s: float = 5.0,
    max_wait_s: float = 600.0,
) -> list[DelayObservation]:
    """Find waits (and no-wait crossings) at junctions the trip passed through.

    A stop is a run of pings that stay within ``stationary_radius_m`` of the
    first ping of the run, within ``junction_radius_m`` of the junction. It is
    kept only if GPS is continuous around it and the trip enters the junction on
    a road that ends there and leaves on a road that starts there.

    Crossings without a stop are recorded as 0 s waits, for signals and for
    junctions where the driver had a real choice of exits.
    """
    if any(
        p.recorded_at.tzinfo is None or p.recorded_at.utcoffset() is None
        for p in observations
    ):
        raise ValueError("GPS timestamps must be timezone-aware")

    points = sorted(observations, key=lambda p: p.recorded_at)
    n = len(points)
    if n < 3:
        return []

    local_edges = _nearby_edges(points, edges)
    node_coords: dict[str, tuple[float, float]] = {}
    incoming: dict[str, list[EdgeMeta]] = {}
    outgoing: dict[str, list[EdgeMeta]] = {}
    for edge in local_edges:
        node_coords[edge.from_node] = edge.geometry[0]
        node_coords[edge.to_node] = edge.geometry[-1]
        incoming.setdefault(edge.to_node, []).append(edge)
        outgoing.setdefault(edge.from_node, []).append(edge)

    pos = [(p.lat, p.lng) for p in points]
    times = [p.recorded_at for p in points]

    def linked(i: int) -> bool:
        """Pings i and i+1 are close enough in time to trust as continuous."""
        return 0 < (times[i + 1] - times[i]).total_seconds() <= max_gap_s

    candidate_cache: dict[int, list] = {}

    def candidates(i: int) -> list:
        if i not in candidate_cache:
            found = [
                (_edge_distance_m(pos[i], e), e) for e in local_edges
            ]
            found = [(d, e) for d, e in found if d <= match_radius_m]
            if found:
                best = min(d for d, _ in found)
                found = [(d, e) for d, e in found if d <= best + _EDGE_TOLERANCE_M]
            candidate_cache[i] = found
        return candidate_cache[i]

    result: list[DelayObservation] = []

    for junction_id, location in node_coords.items():
        if junction_id not in incoming or junction_id not in outgoing:
            continue

        dist = [haversine_m(p, location) for p in pos]
        if min(dist) > _REACH_M:
            continue

        def find_ref(first: int, step: int) -> int | None:
            """Nearest ping at least ``leg_min_m`` from the junction, reached
            without a GPS break. It sits clearly on one road, so direction can
            be told from the road network."""
            j = first
            for _ in range(_MAX_REF_STEPS + 1):
                if not 0 <= j < n:
                    return None
                link = min(j, j - step)
                if not 0 <= link < n - 1 or not linked(link):
                    return None
                if dist[j] >= leg_min_m:
                    return j
                j += step
            return None

        def passes(a: int, b: int) -> bool:
            return any(
                distance_to_segment_m(location, pos[m], pos[m + 1]) <= pass_radius_m
                for m in range(a, b)
            )

        def movement(ref_before: int, ref_after: int):
            inbound_id = _unique_edge(
                candidates(ref_before), lambda e: e.to_node == junction_id
            )
            outbound_id = _unique_edge(
                candidates(ref_after), lambda e: e.from_node == junction_id
            )
            if inbound_id is None or outbound_id is None:
                return None
            return edges[inbound_id], edges[outbound_id]

        def make(inbound, outbound, when, wait_s) -> DelayObservation:
            signal = "traffic_signals" in inbound.end_features
            return DelayObservation(
                kind=DelayKind.SIGNAL if signal else DelayKind.TURN,
                junction_id=junction_id,
                driver_id=driver_id,
                observed_at=when,
                wait_s=wait_s,
                inbound_segment=None if signal else inbound.segment_id,
                outbound_segment=None if signal else outbound.segment_id,
            )

        used_pairs: set[int] = set()   # ping pairs explained by a stop here
        done_until = -1                # one observation per pass through the junction

        # 1) Stops at the junction.
        index = 0
        while index < n:
            if dist[index] > junction_radius_m:
                index += 1
                continue

            start = end = index
            while (
                end + 1 < n
                and linked(end)
                and dist[end + 1] <= junction_radius_m
                and haversine_m(pos[start], pos[end + 1]) <= stationary_radius_m
            ):
                end += 1
            index = end + 1

            wait_s = (times[end] - times[start]).total_seconds()
            if wait_s < min_wait_s:
                continue

            # Whatever happens next, this stop must not turn into a 0 s crossing.
            used_pairs.update(range(max(start - 1, 0), end + 1))

            if wait_s > max_wait_s or start <= done_until:
                continue
            if start == 0 or end + 1 >= n:
                continue

            ref_before = find_ref(start - 1, -1)
            ref_after = find_ref(end + 1, +1)
            if ref_before is None or ref_after is None:
                continue
            if not passes(ref_before, ref_after):
                continue

            moved = movement(ref_before, ref_after)
            if moved is None:
                continue

            result.append(make(*moved, times[start], wait_s))
            done_until = ref_after

        # 2) Crossings without a stop.
        k = 0
        while k < n - 1:
            if (
                k in used_pairs
                or not linked(k)
                or min(dist[k], dist[k + 1]) > _REACH_M
                or distance_to_segment_m(location, pos[k], pos[k + 1]) > pass_radius_m
            ):
                k += 1
                continue

            ref_before = find_ref(k, -1)
            ref_after = find_ref(k + 1, +1)
            if ref_before is None or ref_after is None:
                k += 1
                continue
            if any(m in used_pairs for m in range(ref_before, ref_after)):
                k = ref_after
                continue

            moved = movement(ref_before, ref_after)
            if moved is None:
                k += 1
                continue

            inbound, outbound = moved
            signal = "traffic_signals" in inbound.end_features
            exits = {
                e.to_node for e in outgoing[junction_id]
                if e.to_node != inbound.from_node
            }
            if signal or len(exits) >= 2:
                result.append(make(inbound, outbound, times[k], 0.0))
            k = ref_after

    return result
