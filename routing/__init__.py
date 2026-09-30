"""Hierarchy-preserving routing with telemetry overlays.

Cost = Distance / (Speed x Priority). Baseline road-class priorities are always
present; telemetry can only append penalties on top of them.
"""
from .cost import edge_cost, route_cost
from .engine import LocalAStarRouter, RouterBackend, RoutingService
from .graph import RoadGraph
from .graphhopper import GraphHopperRouter, to_graphhopper
from .models import (
    CustomModel, EdgeMeta, Op, RoadClassIs, RouteResult, SegmentExposure, SegmentIs,
    Source, SpeedSample, Statement, Target,
)
from .monitoring import detect_exposures, route_quality
from .road_classes import BASE_PRIORITY, RoadClass, priority_for
from .rule_engine import CompiledModel, baseline_model, merge_models
from .telemetry import TelemetryPolicy, aggregate, derive_rules, road_health

__all__ = [
    "BASE_PRIORITY", "CompiledModel", "CustomModel", "EdgeMeta", "GraphHopperRouter",
    "LocalAStarRouter", "Op", "RoadClass", "RoadClassIs", "RoadGraph", "RouteResult",
    "RouterBackend", "RoutingService", "SegmentExposure", "SegmentIs", "Source",
    "SpeedSample", "Statement", "Target", "TelemetryPolicy", "aggregate", "baseline_model",
    "derive_rules", "detect_exposures", "edge_cost", "merge_models", "priority_for",
    "road_health", "route_cost", "route_quality", "to_graphhopper",
]
