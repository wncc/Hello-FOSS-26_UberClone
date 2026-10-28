
"""Conservative GPS-to-road matching for routing telemetry."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .graph import haversine_m
from .models import EdgeMeta, SpeedSample
from .vehicles import VehicleType


@dataclass(frozen=True)
class GPSObservation:
    lat: float
    lng: float
    recorded_at: datetime


def coordinates(
    point: GPSObservation | tuple[float, float],
) -> tuple[float, float]:
    """Accept either a GPS observation or a coordinate tuple."""
    if isinstance(point, GPSObservation):
        return point.lat, point.lng
    return point


def distance_to_segment_m(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Approximate distance from a point to a short road segment."""
    latitude = math.radians(point[0])
    meters_lat = 111_195.0
    meters_lng = meters_lat * math.cos(latitude)

    ax = (start[1] - point[1]) * meters_lng
    ay = (start[0] - point[0]) * meters_lat
    bx = (end[1] - point[1]) * meters_lng
    by = (end[0] - point[0]) * meters_lat

    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy

    if length_sq == 0:
        return haversine_m(point, start)

    fraction = max(
        0.0,
        min(1.0, -(ax * dx + ay * dy) / length_sq),
    )

    return math.hypot(
        ax + fraction * dx,
        ay + fraction * dy,
    )

class SegmentIndex:
    """Grid index: finds roads near a point without scanning every edge."""

    def __init__(self, edges: dict[str, EdgeMeta], cell_deg: float = 0.001):
        self.cell_deg = cell_deg
        self._cells: dict[tuple[int, int], list[str]] = {}

        for segment_id, edge in edges.items():
            geometry = edge.geometry
            if len(geometry) < 2:
                continue
            cells: set[tuple[int, int]] = set()
            for a, b in zip(geometry, geometry[1:]):
                r0, r1 = sorted((self._cell(a[0]), self._cell(b[0])))
                c0, c1 = sorted((self._cell(a[1]), self._cell(b[1])))
                cells.update(
                    (r, c)
                    for r in range(r0, r1 + 1)
                    for c in range(c0, c1 + 1)
                )
            for cell in cells:
                self._cells.setdefault(cell, []).append(segment_id)

    def _cell(self, degrees: float) -> int:
        return math.floor(degrees / self.cell_deg)

    def candidates(
        self, point: tuple[float, float], radius_m: float
    ) -> set[str]:
        lat, lng = point
        pad_lat = radius_m * 1.1 / 111_195.0
        pad_lng = pad_lat / max(math.cos(math.radians(lat)), 0.01)
        found: set[str] = set()
        for r in range(self._cell(lat - pad_lat), self._cell(lat + pad_lat) + 1):
            for c in range(self._cell(lng - pad_lng), self._cell(lng + pad_lng) + 1):
                found.update(self._cells.get((r, c), ()))
        return found

def nearest_segment(
    point: GPSObservation | tuple[float, float],
    edges: dict[str, EdgeMeta],
    max_distance_m: float = 30.0,
    ambiguity_m: float = 3.0,
    index: SegmentIndex | None = None,
) -> str | None:
    """Find the closest road, rejecting ambiguous parallel roads."""
    location = coordinates(point)
    if index is None:
        index = SegmentIndex(edges)
    candidates = []

    for segment_id in index.candidates(location, max_distance_m):
        geometry = edges[segment_id].geometry

        distance = min(
            distance_to_segment_m(location, a, b)
            for a, b in zip(geometry, geometry[1:])
        )

        if distance <= max_distance_m:
            candidates.append((distance, segment_id))

    if not candidates:
        return None

    candidates.sort()
    best_distance, best_id = candidates[0]

    if len(candidates) > 1:
        second_distance, second_id = candidates[1]

        if second_distance - best_distance < ambiguity_m:
            best_edge = edges[best_id]
            second_edge = edges[second_id]

            # Connected roads can meet at a junction.
            connected = (
                best_edge.to_node == second_edge.from_node
                or second_edge.to_node == best_edge.from_node
            )

            if not connected:
                return None

    return best_id

def match_gps_sequence(
    points: list[GPSObservation | tuple[float, float]],
    edges: dict[str, EdgeMeta],
    max_distance_m: float = 30.0,
    index: SegmentIndex | None = None,
) -> list[str]:
    """Return the latest uninterrupted sequence of road matches."""
    index = index or SegmentIndex(edges)
    segments: list[str] = []

    for point in points:
        segment_id = nearest_segment(
            point, edges, max_distance_m, index=index
        )

        if segment_id is None:
            segments.clear()
            continue

        if not segments or segments[-1] != segment_id:
            segments.append(segment_id)

    return segments


def segment_progress(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Return approximate progress along a straight directed road."""
    latitude = math.radians(point[0])
    meters_lat = 111_195.0
    meters_lng = meters_lat * math.cos(latitude)

    ax = (start[1] - point[1]) * meters_lng
    ay = (start[0] - point[0]) * meters_lat
    bx = (end[1] - point[1]) * meters_lng
    by = (end[0] - point[0]) * meters_lat

    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy

    if length_sq == 0:
        return 0.0

    return max(
        0.0,
        min(1.0, -(ax * dx + ay * dy) / length_sq),
    )


def complete_traversal(
    start_progress: float,
    end_progress: float,
    boundary_tolerance: float = 0.10,
) -> bool:
    """Require observations near both ends of a directed road."""
    return (
        0.0 <= start_progress <= boundary_tolerance
        and 1.0 - boundary_tolerance <= end_progress <= 1.0
        and end_progress > start_progress
    )


def traversal_speed_kmh(
    distance_m: float,
    started_at: datetime,
    ended_at: datetime,
    max_duration_s: float = 300.0,
    max_speed_kmh: float = 130.0,
) -> float | None:
    """Calculate speed only when duration and speed are plausible."""
    duration_s = (ended_at - started_at).total_seconds()

    if distance_m <= 0 or not 0 < duration_s <= max_duration_s:
        return None

    speed = distance_m / duration_s * 3.6

    if speed > max_speed_kmh:
        return None

    return speed


def speed_sample_from_observations(
    observations: list[GPSObservation],
    edge: EdgeMeta,
    driver_id: str,
    trip_id: str,
    vehicle: VehicleType = VehicleType.CAR,
) -> SpeedSample | None:
    """Build a candidate speed sample for one straight road."""
    if len(observations) < 2 or len(edge.geometry) != 2:
        return None

    start, end = edge.geometry
    ordered = sorted(
        observations,
        key=lambda p: p.recorded_at,
    )

    for point in ordered:
        if distance_to_segment_m(
            (point.lat, point.lng), start, end
        ) > 30:
            return None

    progress = [
        segment_progress(
            (point.lat, point.lng), start, end
        )
        for point in ordered
    ]

    if not complete_traversal(progress[0], progress[-1]):
        return None

    if any(
        b < a - 0.02
        for a, b in zip(progress, progress[1:])
    ):
        return None

    for index, (previous, current) in enumerate(
        zip(ordered, ordered[1:])
    ):
        elapsed = (
            current.recorded_at - previous.recorded_at
        ).total_seconds()

        if not 0 < elapsed <= 60:
            return None

        distance = (
            progress[index + 1] - progress[index]
        ) * edge.distance_m

        if distance > 0 and distance / elapsed * 3.6 > 130:
            return None

    observed_distance_m = (
        progress[-1] - progress[0]
    ) * edge.distance_m

    speed = traversal_speed_kmh(
        observed_distance_m,
        ordered[0].recorded_at,
        ordered[-1].recorded_at,
    )

    if speed is None:
        return None

    return SpeedSample(
        edge.segment_id,
        driver_id,
        trip_id,
        speed,
        ordered[-1].recorded_at,
        vehicle,
    )


def group_observations_by_segment(
    observations: list[GPSObservation],
    edges: dict[str, EdgeMeta],
    max_distance_m: float = 30.0,
    max_gap_s: float = 60.0,
    index: SegmentIndex | None = None,
) -> list[tuple[str | None, list[GPSObservation]]]:
    """Group consecutive road observations, preserving tracking breaks."""
    index = index or SegmentIndex(edges)
    groups: list[
        tuple[str | None, list[GPSObservation]]
    ] = []

    previous: GPSObservation | None = None

    for observation in sorted(
        observations,
        key=lambda p: p.recorded_at,
    ):
        if previous is not None:
            elapsed = (
                observation.recorded_at - previous.recorded_at
            ).total_seconds()

            if not 0 < elapsed <= max_gap_s:
                if not groups or groups[-1][0] is not None:
                    groups.append((None, []))

        segment_id = nearest_segment(
            observation,
            edges,
            max_distance_m,
            index=index,
        )

        if segment_id is None:
            if not groups or groups[-1][0] is not None:
                groups.append((None, []))
        elif groups and groups[-1][0] == segment_id:
            groups[-1][1].append(observation)
        else:
            groups.append((segment_id, [observation]))

        previous = observation

    return groups

def extract_speed_samples(
    observations: list[GPSObservation],
    edges: dict[str, EdgeMeta],
    driver_id: str,
    trip_id: str,
    vehicle: VehicleType = VehicleType.CAR,
    index: SegmentIndex | None = None,
) -> list[SpeedSample]:
    """Extract candidate speed samples from uninterrupted GPS groups."""
    samples: list[SpeedSample] = []

    groups = group_observations_by_segment(
        observations, edges, index=index
    )

    for segment_id, points in groups:
        if segment_id is None:
            continue

        sample = speed_sample_from_observations(
            points,
            edges[segment_id],
            driver_id,
            trip_id,
            vehicle,
        )

        if sample is not None:
            samples.append(sample)

    return samples
