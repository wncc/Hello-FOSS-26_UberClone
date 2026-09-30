"""Route quality monitoring and deviation detection.

Inputs are segment sequences: the route we planned and the route the driver
actually drove (as produced by a map-matcher such as GraphHopper Map Matching).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import SegmentExposure


def detect_exposures(planned: list[str], actual: list[str], trip_id: str, driver_id: str,
                     observed_at: datetime) -> list[SegmentExposure]:
    """Emit one exposure per planned segment the driver reached, up to the first deviation.

    Once a driver deviates the app reroutes, so the rest of the old plan is not
    evidence about those roads; the new plan should be fed in as a new call.
    """
    events: list[SegmentExposure] = []
    for i, planned_seg in enumerate(planned):
        followed = i < len(actual) and actual[i] == planned_seg
        if not followed and i >= len(actual):
            break  # trip ended/cancelled: not a deviation
        events.append(SegmentExposure(planned_seg, driver_id, trip_id, followed, observed_at))
        if not followed:
            break
    return events


@dataclass(frozen=True)
class RouteQuality:
    trip_id: str
    followed_fraction: float      # share of the planned route driven as planned
    deviated_at: str | None       # first avoided planned segment
    eta_error_ratio: float | None # (actual - planned) / planned
    accepted: bool                # driver accepted the dispatched route


def route_quality(trip_id: str, planned: list[str], actual: list[str],
                  planned_eta_s: float | None, actual_duration_s: float | None,
                  accepted: bool = True) -> RouteQuality:
    matched = 0
    deviated_at = None
    for i, seg in enumerate(planned):
        if i < len(actual) and actual[i] == seg:
            matched += 1
            continue
        if i < len(actual):
            deviated_at = seg
        break
    eta_error = None
    if planned_eta_s and actual_duration_s is not None:
        eta_error = (actual_duration_s - planned_eta_s) / planned_eta_s
    return RouteQuality(
        trip_id=trip_id,
        followed_fraction=matched / len(planned) if planned else 1.0,
        deviated_at=deviated_at,
        eta_error_ratio=eta_error,
        accepted=accepted,
    )
