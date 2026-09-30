"""Hierarchy-preserving routing with telemetry overlays.

Cost = Distance / (Speed x Priority). Baseline road-class priorities are always
present; telemetry can only append penalties on top of them.
"""
from .cost import edge_cost, route_cost, route_eta_s
from .engine import LocalAStarRouter, RouterBackend, RoutingService
from .graph import RoadGraph
from .graphhopper import GraphHopperRouter, to_graphhopper
from .models import (
    CustomModel, EdgeMeta, InArea, Op, RestrictedZone, RoadAccess, RoadAccessIs, RoadClassIs, RouteResult,
    SegmentExposure, SegmentIs, Source, SpeedLimitSource, SpeedSample, Statement, Target, Toll, TollIs,
    ZoneKind, expected_speed_kmh,
)
from .monitoring import detect_exposures, route_quality
from .restrictions import RouteOptions
from .road_classes import BASE_PRIORITY, UNIFORM_SPEED_KMH, RoadClass, priority_for
from .rule_engine import CompiledModel, baseline_model, merge_models
from .speed_model import FittedSpeedModel, SegmentKind, SpeedModelPolicy, fit_speed_model
from .telemetry import TelemetryPolicy, aggregate, derive_rules, road_health
from .time_buckets import IST, TimeBuckets

__all__ = [
    "BASE_PRIORITY", "UNIFORM_SPEED_KMH", "CompiledModel", "CustomModel", "EdgeMeta", "GraphHopperRouter",
    "LocalAStarRouter", "Op", "RoadClass", "RoadClassIs", "RoadGraph", "RouteResult",
    "RouterBackend", "RoutingService", "SegmentExposure", "SegmentIs", "Source",
    "SpeedSample", "Statement", "Target", "TelemetryPolicy", "aggregate", "baseline_model",
    "derive_rules", "detect_exposures", "edge_cost", "merge_models", "priority_for",
    "road_health", "route_cost", "route_quality", "to_graphhopper",
    "route_eta_s", "FittedSpeedModel",
    "SegmentKind", "SpeedModelPolicy", "fit_speed_model", "IST", "TimeBuckets",
    "InArea", "RestrictedZone", "RoadAccess", "RoadAccessIs", "RouteOptions", "SpeedLimitSource",
    "Toll", "TollIs", "ZoneKind", "expected_speed_kmh",
]
