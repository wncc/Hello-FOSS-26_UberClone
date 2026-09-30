"""Rule engine: baseline model, validation, merging, and per-edge evaluation.

Composition is order-independent by construction:
  * speed:    limit_to composes with min(), multiply_by with product
  * priority: multiply_by composes with product, limit_to with min()
Both are commutative, so telemetry overlays can be appended in any order
without rewriting or reordering the baseline.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone

from .models import (
    EDGE_AVERAGE_SPEED, Always, CustomModel, EdgeEvaluation, EdgeMeta, Op,
    RoadClassIs, SegmentIs, Source, Statement, Target,
)
from .road_classes import BASE_PRIORITY, RoadClass

MIN_TELEMETRY_PRIORITY = 0.01   # "effectively dead" but still routable as last resort
MIN_SPEED_KMH = 5.0


class RuleValidationError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# Baseline
# --------------------------------------------------------------------------- #

def baseline_model(distance_influence: float = 0.0) -> CustomModel:
    speed = [Statement(Target.SPEED, Always(), Op.LIMIT_TO, EDGE_AVERAGE_SPEED,
                       Source.BASELINE, "base.speed")]
    priority = [
        Statement(Target.PRIORITY, RoadClassIs(rc), Op.MULTIPLY_BY, p,
                  Source.BASELINE, f"base.priority.{rc.value.lower()}")
        for rc, p in BASE_PRIORITY.items() if p < 1.0
    ]
    return CustomModel(speed=speed, priority=priority, distance_influence=distance_influence)


# --------------------------------------------------------------------------- #
# Validation: overlays may only penalize, never boost.
# --------------------------------------------------------------------------- #

def validate(stmt: Statement) -> None:
    v = stmt.value
    if stmt.target is Target.SPEED:
        if stmt.op is Op.LIMIT_TO:
            if v == EDGE_AVERAGE_SPEED:
                if stmt.source is not Source.BASELINE:
                    raise RuleValidationError(f"{stmt.rule_id}: only baseline may reference {v}")
                return
            if not isinstance(v, (int, float)) or v < MIN_SPEED_KMH:
                raise RuleValidationError(f"{stmt.rule_id}: speed limit_to must be >= {MIN_SPEED_KMH}")
        elif not isinstance(v, (int, float)) or not 0 < v <= 1:
            raise RuleValidationError(f"{stmt.rule_id}: speed multiply_by must be in (0, 1]")
        return

    if not isinstance(v, (int, float)) or v > 1 or v < 0:
        raise RuleValidationError(f"{stmt.rule_id}: priority value must be in [0, 1]")
    floor = 0.0 if stmt.source in (Source.OPS, Source.BASELINE) else MIN_TELEMETRY_PRIORITY
    if v < floor:
        raise RuleValidationError(
            f"{stmt.rule_id}: {stmt.source.value} priority must be >= {floor} (only ops may block)")


# --------------------------------------------------------------------------- #
# Merge
# --------------------------------------------------------------------------- #

_SOURCE_ORDER = {s: i for i, s in enumerate(Source)}


def merge_models(base: CustomModel, overlays: list[list[Statement]],
                 now: datetime | None = None) -> CustomModel:
    """Append validated, non-expired overlay statements to the baseline.

    Baseline statements are kept verbatim and first. Overlay duplicates from the
    same source that target the same (target, condition, op) keep only the
    strictest value, so a re-emitted or overlapping rule never compounds.
    """
    now = now or datetime.now(timezone.utc)
    strictest: dict[tuple, Statement] = {}
    for stmt in (s for layer in overlays for s in layer):
        if not stmt.is_active(now):
            continue
        validate(stmt)
        key = (stmt.target, stmt.condition, stmt.op, stmt.source)
        current = strictest.get(key)
        if current is None or stmt.value < current.value:
            strictest[key] = stmt

    ordered = sorted(strictest.values(), key=lambda s: (_SOURCE_ORDER[s.source], s.rule_id))
    return CustomModel(
        speed=[*base.speed, *(s for s in ordered if s.target is Target.SPEED)],
        priority=[*base.priority, *(s for s in ordered if s.target is Target.PRIORITY)],
        distance_influence=base.distance_influence,
    )


# --------------------------------------------------------------------------- #
# Evaluation (local mirror of what GraphHopper computes per edge)
# --------------------------------------------------------------------------- #

class CompiledModel:
    """Indexes statements by condition so evaluating an edge is O(matching rules)."""

    def __init__(self, model: CustomModel):
        self.model = model
        self._always: dict[Target, list[Statement]] = defaultdict(list)
        self._by_class: dict[tuple[Target, RoadClass], list[Statement]] = defaultdict(list)
        self._by_segment: dict[tuple[Target, str], list[Statement]] = defaultdict(list)
        for s in model.statements():
            c = s.condition
            if isinstance(c, Always):
                self._always[s.target].append(s)
            elif isinstance(c, RoadClassIs):
                self._by_class[(s.target, c.road_class)].append(s)
            elif isinstance(c, SegmentIs):
                self._by_segment[(s.target, c.segment_id)].append(s)

    def _matching(self, target: Target, edge: EdgeMeta) -> list[Statement]:
        seg = [s for s in self._by_segment.get((target, edge.segment_id), ())
               if s.condition.road_class in (None, edge.road_class)]
        return [*self._always.get(target, ()), *self._by_class.get((target, edge.road_class), ()), *seg]

    def evaluate(self, edge: EdgeMeta) -> EdgeEvaluation:
        applied: list[str] = []

        speed = math.inf
        for s in self._matching(Target.SPEED, edge):
            value = edge.speed_kmh if s.value == EDGE_AVERAGE_SPEED else float(s.value)
            speed = min(speed, value) if s.op is Op.LIMIT_TO else speed * value
            applied.append(s.rule_id)
        if math.isinf(speed):
            speed = edge.speed_kmh

        priority = 1.0
        for s in self._matching(Target.PRIORITY, edge):
            priority = min(priority, s.value) if s.op is Op.LIMIT_TO else priority * s.value
            applied.append(s.rule_id)

        return EdgeEvaluation(edge.segment_id, speed, priority, tuple(applied))
