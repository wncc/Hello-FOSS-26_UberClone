"""Turn raw telemetry into road health scores and guarded override rules.

Guardrails, in the order they apply:
  1. Time decay       old observations fade (half-life), so roads can recover.
  2. Evidence tiers   NONE / SOFT / HARD from sample weight, distinct drivers, distinct days.
  3. Shrinkage        estimates are pulled toward "normal" until data outweighs the prior.
  4. Hysteresis       a rule turns on at one threshold and off at a looser one (no flapping).
  5. Soft caps        SOFT evidence can only slow/penalize a road by a bounded amount.
  6. Hierarchy floor  SOFT evidence can never push a main road below residential baseline.
  7. TTL              rules expire unless the next run re-emits them.

With a TrafficContext (a fitted speed_model.FittedSpeedModel):
  * speed samples are de-trended first, so the speed rule reflects road
    *condition* only; time-of-week traffic is applied per request instead.
  * avoidance during the segment's peak hours is counted separately and can
    only produce a rule that is active during those peak hours.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol

from .models import (
    EdgeMeta, Evidence, Op, RoadHealth, SegmentExposure, SegmentIs, SegmentStats,
    Source, SpeedSample, Statement, Target,
)
from .road_classes import RoadClass, hierarchy_floor_rate, priority_for
from .rule_engine import MIN_SPEED_KMH, MIN_TELEMETRY_PRIORITY


@dataclass(frozen=True)
class TelemetryPolicy:
    half_life_days: float = 14.0
    window_days: float = 60.0
    rule_ttl: timedelta = timedelta(days=7)

    # Speed signal
    speed_prior_weight: float = 20.0      # pseudo-samples at the expected speed
    speed_soft_min_weight: float = 20.0
    speed_soft_min_drivers: int = 5
    speed_hard_min_weight: float = 150.0
    speed_hard_min_drivers: int = 20
    speed_hard_min_days: int = 3
    speed_ratio_enter: float = 0.70       # rule turns on below this observed/expected ratio
    speed_ratio_exit: float = 0.80        # ...and only turns off above this one
    soft_speed_floor_ratio: float = 0.50  # SOFT can at most halve the speed

    # Deviation signal (Beta prior ~= 5% background avoidance)
    avoid_prior_a: float = 1.0
    avoid_prior_b: float = 19.0
    avoid_soft_min_weight: float = 20.0
    avoid_soft_min_drivers: int = 5
    avoid_hard_min_weight: float = 50.0
    avoid_hard_min_drivers: int = 10
    avoid_hard_min_days: int = 3
    avoid_rate_enter: float = 0.30
    avoid_rate_exit: float = 0.20
    avoid_rate_kill: float = 0.80         # HARD + this rate => priority 0.01
    soft_priority_floor: float = 0.70     # SOFT can at most multiply priority by 0.7


DEFAULT_POLICY = TelemetryPolicy()


class TrafficContext(Protocol):
    def detrend(self, sample: SpeedSample) -> float: ...
    def is_peak(self, segment_id: str, when: datetime) -> bool: ...
    def peak_buckets(self, edge: EdgeMeta) -> frozenset[int]: ...


def speed_rule_id(segment_id: str) -> str:
    return f"tele.speed.{segment_id}"


def deviation_rule_id(segment_id: str) -> str:
    return f"tele.dev.{segment_id}"


def peak_deviation_rule_id(segment_id: str) -> str:
    return f"tele.dev.peak.{segment_id}"


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #

def decay_weight(age: timedelta, half_life_days: float) -> float:
    return 0.5 ** (max(age.total_seconds(), 0.0) / 86400.0 / half_life_days)


def _weighted_median(pairs: list[tuple[float, float]]) -> float:
    pairs = sorted(pairs)
    half = sum(w for _, w in pairs) / 2.0
    acc = 0.0
    for value, w in pairs:
        acc += w
        if acc >= half:
            return value
    return pairs[-1][0]


def aggregate(speed_samples: list[SpeedSample], exposures: list[SegmentExposure],
              now: datetime, policy: TelemetryPolicy = DEFAULT_POLICY,
              traffic: TrafficContext | None = None) -> dict[str, SegmentStats]:
    window = timedelta(days=policy.window_days)
    speeds: dict[str, list[tuple[float, float]]] = defaultdict(list)
    speed_drivers: dict[str, set] = defaultdict(set)
    speed_days: dict[str, set] = defaultdict(set)
    exp_w: dict[str, float] = defaultdict(float)
    dev_w: dict[str, float] = defaultdict(float)
    dev_drivers: dict[str, set] = defaultdict(set)
    dev_days: dict[str, set] = defaultdict(set)
    peak_exp_w: dict[str, float] = defaultdict(float)
    peak_dev_w: dict[str, float] = defaultdict(float)
    peak_dev_drivers: dict[str, set] = defaultdict(set)
    peak_dev_days: dict[str, set] = defaultdict(set)

    for s in speed_samples:
        age = now - s.observed_at
        if age > window or s.speed_kmh < 0:
            continue
        speed = s.speed_kmh * traffic.detrend(s) if traffic else s.speed_kmh
        speeds[s.segment_id].append((speed, decay_weight(age, policy.half_life_days)))
        speed_drivers[s.segment_id].add(s.driver_id)
        speed_days[s.segment_id].add(s.observed_at.date())

    for e in exposures:
        age = now - e.observed_at
        if age > window:
            continue
        w = decay_weight(age, policy.half_life_days)
        peak = traffic is not None and traffic.is_peak(e.segment_id, e.observed_at)
        ew, dw, dd, ds = ((peak_exp_w, peak_dev_w, peak_dev_drivers, peak_dev_days) if peak
                          else (exp_w, dev_w, dev_drivers, dev_days))
        ew[e.segment_id] += w
        if not e.followed:
            dw[e.segment_id] += w
            dd[e.segment_id].add(e.driver_id)
            ds[e.segment_id].add(e.observed_at.date())

    stats = {}
    for seg in set(speeds) | set(exp_w) | set(peak_exp_w):
        pairs = speeds.get(seg, [])
        stats[seg] = SegmentStats(
            segment_id=seg,
            speed_weight=sum(w for _, w in pairs),
            speed_drivers=len(speed_drivers.get(seg, ())),
            speed_days=len(speed_days.get(seg, ())),
            median_speed_kmh=_weighted_median(pairs) if pairs else None,
            exposure_weight=exp_w.get(seg, 0.0),
            deviation_weight=dev_w.get(seg, 0.0),
            deviating_drivers=len(dev_drivers.get(seg, ())),
            deviation_days=len(dev_days.get(seg, ())),
            peak_exposure_weight=peak_exp_w.get(seg, 0.0),
            peak_deviation_weight=peak_dev_w.get(seg, 0.0),
            peak_deviating_drivers=len(peak_dev_drivers.get(seg, ())),
            peak_deviation_days=len(peak_dev_days.get(seg, ())),
        )
    return stats


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

def speed_evidence(s: SegmentStats, p: TelemetryPolicy = DEFAULT_POLICY) -> Evidence:
    if s.median_speed_kmh is None:
        return Evidence.NONE
    if (s.speed_weight >= p.speed_hard_min_weight and s.speed_drivers >= p.speed_hard_min_drivers
            and s.speed_days >= p.speed_hard_min_days):
        return Evidence.HARD
    if s.speed_weight >= p.speed_soft_min_weight and s.speed_drivers >= p.speed_soft_min_drivers:
        return Evidence.SOFT
    return Evidence.NONE


def deviation_evidence(s: SegmentStats, p: TelemetryPolicy = DEFAULT_POLICY) -> Evidence:
    if (s.exposure_weight >= p.avoid_hard_min_weight and s.deviating_drivers >= p.avoid_hard_min_drivers
            and s.deviation_days >= p.avoid_hard_min_days):
        return Evidence.HARD
    if s.exposure_weight >= p.avoid_soft_min_weight and s.deviating_drivers >= p.avoid_soft_min_drivers:
        return Evidence.SOFT
    return Evidence.NONE


def shrunk_speed_ratio(s: SegmentStats, expected_kmh: float, p: TelemetryPolicy = DEFAULT_POLICY) -> float:
    if s.median_speed_kmh is None or expected_kmh <= 0:
        return 1.0
    k = p.speed_prior_weight
    blended = (s.speed_weight * s.median_speed_kmh + k * expected_kmh) / (s.speed_weight + k)
    return min(1.0, blended / expected_kmh)


def shrunk_avoidance_rate(s: SegmentStats, p: TelemetryPolicy = DEFAULT_POLICY) -> float:
    return (s.deviation_weight + p.avoid_prior_a) / (s.exposure_weight + p.avoid_prior_a + p.avoid_prior_b)


def _peak_view(s: SegmentStats) -> SegmentStats:
    return replace(s, exposure_weight=s.peak_exposure_weight, deviation_weight=s.peak_deviation_weight,
                   deviating_drivers=s.peak_deviating_drivers, deviation_days=s.peak_deviation_days)


def road_health(edge: EdgeMeta, s: SegmentStats, p: TelemetryPolicy = DEFAULT_POLICY) -> RoadHealth:
    ratio = shrunk_speed_ratio(s, edge.speed_kmh, p)
    rate = shrunk_avoidance_rate(s, p)
    dev_evidence = deviation_evidence(s, p)
    peak = _peak_view(s)
    return RoadHealth(
        segment_id=edge.segment_id,
        speed_ratio=ratio,
        avoidance_rate=rate,
        health=round(0.5 * ratio + 0.5 * (1.0 - rate), 4),
        speed_evidence=speed_evidence(s, p),
        deviation_evidence=dev_evidence,
        peak_avoidance_rate=shrunk_avoidance_rate(peak, p) if s.peak_exposure_weight else None,
        peak_deviation_evidence=deviation_evidence(peak, p),
        suspected_map_error=(dev_evidence is Evidence.HARD and rate >= p.avoid_rate_kill
                             and s.speed_weight == 0),
    )


# --------------------------------------------------------------------------- #
# Rule derivation
# --------------------------------------------------------------------------- #

def _proposed_speed(edge: EdgeMeta, h: RoadHealth, was_active: bool, p: TelemetryPolicy) -> float | None:
    if h.speed_evidence is Evidence.NONE:
        return None
    threshold = p.speed_ratio_exit if was_active else p.speed_ratio_enter
    if h.speed_ratio >= threshold:
        return None
    speed = edge.speed_kmh * h.speed_ratio
    if h.speed_evidence is Evidence.SOFT:
        speed = max(speed, edge.speed_kmh * p.soft_speed_floor_ratio)
    return max(speed, MIN_SPEED_KMH)


def _proposed_priority(h: RoadHealth, was_active: bool, p: TelemetryPolicy) -> float | None:
    if h.deviation_evidence is Evidence.NONE:
        return None
    threshold = p.avoid_rate_exit if was_active else p.avoid_rate_enter
    if h.avoidance_rate < threshold:
        return None
    if h.deviation_evidence is Evidence.HARD:
        if h.avoidance_rate >= p.avoid_rate_kill:
            return MIN_TELEMETRY_PRIORITY
        return max(1.0 - h.avoidance_rate, MIN_TELEMETRY_PRIORITY)
    return max(1.0 - h.avoidance_rate, p.soft_priority_floor)


def _apply_hierarchy_floor(edge: EdgeMeta, speed: float | None, mult: float | None,
                           priorities: dict[RoadClass, float] | None = None) -> tuple[float | None, float | None]:
    """Relax SOFT penalties so a main road stays cheaper per km than a residential street."""
    floor = hierarchy_floor_rate(edge.road_class, priorities)
    base_p = priority_for(edge.road_class, priorities)
    v = speed if speed is not None else edge.speed_kmh
    m = mult if mult is not None else 1.0
    if floor <= 0 or v * base_p * m >= floor:
        return speed, mult
    m = min(1.0, max(m, floor / (v * base_p)))
    if v * base_p * m < floor:
        v = floor / (base_p * m)
    return (v if v < edge.speed_kmh else None), (m if m < 1.0 else None)


def derive_rules(edges: dict[str, EdgeMeta], stats: dict[str, SegmentStats], now: datetime,
                 previously_active: set[str] = frozenset(),
                 policy: TelemetryPolicy = DEFAULT_POLICY,
                 traffic: TrafficContext | None = None,
                 priorities: dict[RoadClass, float] | None = None) -> tuple[list[Statement], list[RoadHealth]]:
    rules: list[Statement] = []
    health: list[RoadHealth] = []
    expires = now + policy.rule_ttl

    for seg_id, s in sorted(stats.items()):
        edge = edges.get(seg_id)
        if edge is None:
            continue  # segment disappeared from the map; drop silently
        h = road_health(edge, s, policy)
        health.append(h)

        speed = _proposed_speed(edge, h, speed_rule_id(seg_id) in previously_active, policy)
        mult = _proposed_priority(h, deviation_rule_id(seg_id) in previously_active, policy)
        if Evidence.HARD not in (h.speed_evidence, h.deviation_evidence):
            speed, mult = _apply_hierarchy_floor(edge, speed, mult, priorities)

        cond = SegmentIs(seg_id, edge.road_class)
        if speed is not None:
            rules.append(Statement(
                Target.SPEED, cond, Op.LIMIT_TO, round(speed, 1), Source.TELEMETRY_SPEED,
                speed_rule_id(seg_id), expires_at=expires,
                reason=f"{h.speed_evidence.value}: speed_ratio={h.speed_ratio:.2f}"))
        if mult is not None:
            rules.append(Statement(
                Target.PRIORITY, cond, Op.MULTIPLY_BY, round(mult, 3), Source.TELEMETRY_DEVIATION,
                deviation_rule_id(seg_id), expires_at=expires,
                reason=f"{h.deviation_evidence.value}: avoidance_rate={h.avoidance_rate:.2f}"))

        if traffic is not None and h.peak_avoidance_rate is not None:
            peak_rule = _peak_rule(edge, h, mult, peak_deviation_rule_id(seg_id) in previously_active,
                                   traffic, expires, policy, priorities)
            if peak_rule:
                rules.append(peak_rule)
    return rules, health


def _peak_rule(edge: EdgeMeta, h: RoadHealth, permanent_mult: float | None, was_active: bool,
               traffic: TrafficContext, expires: datetime, p: TelemetryPolicy,
               priorities: dict[RoadClass, float] | None = None) -> Statement | None:
    """Avoidance seen only at rush hour: penalize the segment only in its peak buckets."""
    view = replace(h, avoidance_rate=h.peak_avoidance_rate, deviation_evidence=h.peak_deviation_evidence)
    mult = _proposed_priority(view, was_active, p)
    if mult is not None and view.deviation_evidence is not Evidence.HARD:
        _, mult = _apply_hierarchy_floor(edge, None, mult, priorities)
    if mult is None or (permanent_mult is not None and mult >= permanent_mult):
        return None
    buckets = traffic.peak_buckets(edge)
    if not buckets:
        return None
    return Statement(
        Target.PRIORITY, SegmentIs(edge.segment_id, edge.road_class), Op.MULTIPLY_BY, round(mult, 3),
        Source.TELEMETRY_DEVIATION, peak_deviation_rule_id(edge.segment_id), expires_at=expires,
        active_buckets=buckets,
        reason=f"peak {view.deviation_evidence.value}: avoidance_rate={view.avoidance_rate:.2f}")
