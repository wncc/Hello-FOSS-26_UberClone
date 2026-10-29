"""Separate permanent road condition from time-of-week traffic.

Per observation, on the log scale (effects multiply, like the cost formula):

    r = ln(expected_speed / observed_speed) = c[s] + t[g, b] + u[s, b] + noise

    c[s]     condition of segment s: slowness that is there even when the road is empty
    t[g, b]  traffic shared by group g (road class; add a zone later) in time bucket b, >= 0
    u[s, b]  segment s's own extra traffic in bucket b (e.g. a school gate at 8 am)

Anchoring: each group's quietest well-observed buckets define t = 0. So
"condition" = slowness that persists at the quietest time of the week, and
"traffic" = everything on top of it that follows the clock.

Fitted by backfitting: each term is a weighted mean of what the others leave
unexplained, shrunk toward 0 ("as expected"). Sparse
segments therefore borrow strength from their group instead of overfitting.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Hashable, Iterable

from .models import EdgeMeta, Op, RoadClassIs, Source, SpeedSample, Statement, Target
from .road_classes import MAIN_ROAD_CLASSES, RoadClass
from .time_buckets import BUCKET_COUNT, SATURDAY, SUNDAY, WEEKDAY, TimeBuckets, daytype_of, hour_of


def default_group(edge: EdgeMeta) -> str:
    """Traffic is learned per group. Start with road class; add a zone (e.g. H3 res 7) later."""
    return edge.road_class.value

# Starting weekday slowdown multipliers by (start_hour, end_hour_inclusive, main_road, minor_road).
# Proposed starting values for a large Indian city (issue 001, step 2).
_WEEKDAY_SLOWDOWN_BANDS: tuple[tuple[int, int, float, float], ...] = (
    (0, 5, 1.0, 1.0),
    (6, 7, 1.15, 1.1),
    (8, 10, 1.8, 1.4),
    (11, 16, 1.4, 1.2),
    (17, 20, 2.0, 1.5),
    (21, 23, 1.2, 1.1),
)

_DAYTYPE_EXCESS_SCALE: dict[int, float] = {
    WEEKDAY: 1.0,
    SATURDAY: 0.8,
    SUNDAY: 0.5,
}

_MAIN_GROUP_NAMES: frozenset[str] = frozenset(rc.value for rc in MAIN_ROAD_CLASSES)
_ALL_GROUP_NAMES: frozenset[str] = frozenset(rc.value for rc in RoadClass)


def _weekday_band_slowdown(hour: int, is_main: bool) -> float:
    for lo, hi, main_val, minor_val in _WEEKDAY_SLOWDOWN_BANDS:
        if lo <= hour <= hi:
            return main_val if is_main else minor_val
    return 1.0


@dataclass(frozen=True)
class CongestionPrior:
    """Starting congestion table (road class x weekday/Saturday/Sunday x hour) as a slowdown
    multiplier >= 1.0. Gives the speed model a sensible traffic term ln(slowdown) before
    telemetry arrives, and acts as the shrinkage target as data trickles in."""
    table: dict[tuple[str, int], float] = field(default_factory=dict)

    @classmethod
    def default(cls) -> "CongestionPrior":
        table: dict[tuple[str, int], float] = {}
        for rc in RoadClass:
            is_main = rc in MAIN_ROAD_CLASSES
            for b in range(BUCKET_COUNT):
                base = _weekday_band_slowdown(hour_of(b), is_main)
                scale = _DAYTYPE_EXCESS_SCALE.get(daytype_of(b), 1.0)
                table[(rc.value, b)] = 1.0 + scale * (base - 1.0)
        return cls(table)

    def slowdown(self, group: str | RoadClass, bucket: int) -> float:
        key = group.value if isinstance(group, RoadClass) else group
        if (key, bucket) in self.table:
            return self.table[(key, bucket)]
        rc_key = key.split(":", 1)[0] if ":" in key else key
        if (rc_key, bucket) in self.table:
            return self.table[(rc_key, bucket)]
        if rc_key in _ALL_GROUP_NAMES:
            base = _weekday_band_slowdown(hour_of(bucket), rc_key in _MAIN_GROUP_NAMES)
            scale = _DAYTYPE_EXCESS_SCALE.get(daytype_of(bucket), 1.0)
            return 1.0 + scale * (base - 1.0)
        return 1.0

    def log_slowdown(self, group: str | RoadClass, bucket: int) -> float:
        return math.log(max(1.0, self.slowdown(group, bucket)))


DEFAULT_CONGESTION_PRIOR = CongestionPrior.default()


# --------------------------------------------------------------------------- #
# Per-bucket ETA calibration (issue 001, step 3)
# --------------------------------------------------------------------------- #

_ETA_CLIP_LOG = math.log(3.0)


@dataclass
class EtaCalibrator:
    """Two-stage hierarchical shrinkage calibrator over (predicted_s, actual_s) pairs.

    Each observation's log ratio ln(actual / predicted) is clipped to [-ln 3, +ln 3].
    1. Global log error is shrunk toward 0 with pseudo-count k:
       g = sum(r) / (N + k)
    2. Each bucket's mean is shrunk toward the global error g with pseudo-count k:
       b_log = (sum_b(r) + k * g) / (n_b + k)
    """
    buckets: TimeBuckets
    k: float = 20.0
    clip_log: float = _ETA_CLIP_LOG
    _global_sum: float = 0.0
    _global_count: int = 0
    _bucket_sums: dict[int, float] = field(default_factory=dict)
    _bucket_counts: dict[int, int] = field(default_factory=dict)
    _raw_apes: dict[int, list[float]] = field(default_factory=dict)
    _calibrated_apes: dict[int, list[float]] = field(default_factory=dict)

    def record(self, predicted_s: float, actual_s: float, departed_at: datetime) -> None:
        """Record a completed trip's uncalibrated predicted_s vs. actual_s duration in seconds."""
        if predicted_s <= 0.0 or actual_s <= 0.0:
            return
        b = self.buckets.of(departed_at)
        cal_pred = predicted_s * self.multiplier(b)
        self._raw_apes.setdefault(b, []).append(abs(actual_s - predicted_s) / actual_s)
        self._calibrated_apes.setdefault(b, []).append(abs(actual_s - cal_pred) / actual_s)

        raw_log = math.log(actual_s / predicted_s)
        r = max(-self.clip_log, min(self.clip_log, raw_log))
        self._global_sum += r
        self._global_count += 1
        self._bucket_sums[b] = self._bucket_sums.get(b, 0.0) + r
        self._bucket_counts[b] = self._bucket_counts.get(b, 0) + 1

    def global_log_error(self) -> float:
        if self._global_count == 0:
            return 0.0
        return self._global_sum / (self._global_count + self.k)

    def log_multiplier(self, at: datetime | int) -> float:
        b = at if isinstance(at, int) else self.buckets.of(at)
        g = self.global_log_error()
        n_b = self._bucket_counts.get(b, 0)
        s_b = self._bucket_sums.get(b, 0.0)
        return (s_b + self.k * g) / (n_b + self.k)

    def multiplier(self, at: datetime | int) -> float:
        return math.exp(self.log_multiplier(at))

    def calibrate(self, eta_s: float, at: datetime | int) -> float:
        return eta_s * self.multiplier(at)

    def median_ape(self, bucket: int | None = None, calibrated: bool = True) -> float | None:
        """Median |actual - predicted| / actual. One bucket, or all trips when bucket is None.
        None means no trips yet (not a perfect score)."""
        src = self._calibrated_apes if calibrated else self._raw_apes
        errs = sorted(e for es in src.values() for e in es) if bucket is None else sorted(src.get(bucket, []))
        if not errs:
            return None
        n, mid = len(errs), len(errs) // 2
        return errs[mid] if n % 2 == 1 else 0.5 * (errs[mid - 1] + errs[mid])



@dataclass(frozen=True)
class SpeedModelPolicy:
    half_life_days: float = 28.0
    window_days: float = 56.0              # 8 weekly cycles
    condition_prior_weight: float = 10.0
    traffic_prior_weight: float = 20.0
    local_prior_weight: float = 30.0       # segment-specific traffic needs a lot of evidence
    quiet_bucket_count: int = 3
    min_quiet_bucket_weight: float = 10.0
    iterations: int = 6
    min_log: float = -1.0                  # observed at most e^1 = 2.7x faster than expected
    max_log: float = 3.0                   # ...or 20x slower (clips GPS glitches, parked cars)
    peak_slowdown: float = 1.3             # buckets at or above this count as "peak"
    min_routing_traffic_factor: float = 0.4
    diagnose_min_weight: float = 10.0
    condition_kind_ratio: float = 0.8
    traffic_kind_slowdown: float = 1.4


DEFAULT_SPEED_POLICY = SpeedModelPolicy()


class SegmentKind(str, Enum):
    NORMAL = "normal"
    CONDITION = "condition"   # slow at all hours -> road problem
    TRAFFIC = "traffic"       # slow only at certain hours -> congestion
    BOTH = "both"
    UNKNOWN = "unknown"       # not enough data


@dataclass(frozen=True)
class SegmentDiagnosis:
    segment_id: str
    kind: SegmentKind
    condition_factor: float   # observed quiet-hour speed / map speed
    peak_slowdown: float      # worst time-of-week slowdown on top of condition
    peak_bucket: int
    weight: float
    drivers: int


@dataclass(frozen=True)
class _Obs:
    seg: str
    group: str
    bucket: int
    r: float
    w: float


def _shrunk_means(obs: Iterable[_Obs], key: Callable[[_Obs], Hashable], residual: Callable[[_Obs], float],
                  k: float, target: Callable[[Hashable], float]) -> dict[Hashable, tuple[float, float]]:
    num: dict[Hashable, float] = defaultdict(float)
    den: dict[Hashable, float] = defaultdict(float)
    for o in obs:
        kk = key(o)
        num[kk] += o.w * residual(o)
        den[kk] += o.w
    return {kk: ((num[kk] + k * target(kk)) / (den[kk] + k), den[kk]) for kk in num}


@dataclass
class FittedSpeedModel:
    buckets: TimeBuckets
    group_of: Callable[[EdgeMeta], str]
    policy: SpeedModelPolicy
    edges: dict[str, EdgeMeta]
    condition: dict[str, float] = field(default_factory=dict)
    traffic: dict[tuple[str, int], float] = field(default_factory=dict)
    local: dict[tuple[str, int], float] = field(default_factory=dict)
    weight: dict[str, float] = field(default_factory=dict)
    drivers: dict[str, int] = field(default_factory=dict)
    prior: CongestionPrior | None = None

    # -- lookups ------------------------------------------------------------ #

    def group_traffic_log(self, group: str, bucket: int) -> float:
        if (group, bucket) in self.traffic:
            return self.traffic[(group, bucket)]
        if self.prior is not None:
            return self.prior.log_slowdown(group, bucket)
        return 0.0

    def traffic_log(self, edge: EdgeMeta, bucket: int) -> float:
        return max(0.0, self.group_traffic_log(self.group_of(edge), bucket)
                   + self.local.get((edge.segment_id, bucket), 0.0))

    def slowdown(self, edge: EdgeMeta, when: datetime) -> float:
        return math.exp(self.traffic_log(edge, self.buckets.of(when)))

    def condition_factor(self, segment_id: str) -> float:
        return math.exp(-self.condition.get(segment_id, 0.0))

    def speed_kmh(self, edge: EdgeMeta, when: datetime) -> float:
        """Best estimate of actual driving speed; use this for ETA (never clamped)."""
        return edge.speed_kmh * self.condition_factor(edge.segment_id) / self.slowdown(edge, when)

    # -- TrafficContext (consumed by telemetry.py) ------------------------- #

    def detrend(self, sample: SpeedSample) -> float:
        """Multiplier that removes time-of-week traffic from an observed speed."""
        edge = self.edges.get(sample.segment_id)
        return self.slowdown(edge, sample.observed_at) if edge else 1.0

    def is_peak(self, segment_id: str, when: datetime) -> bool:
        edge = self.edges.get(segment_id)
        return bool(edge) and self.slowdown(edge, when) >= self.policy.peak_slowdown

    def peak_buckets(self, edge: EdgeMeta) -> frozenset[int]:
        threshold = math.log(self.policy.peak_slowdown)
        return frozenset(b for b in range(BUCKET_COUNT) if self.traffic_log(edge, b) >= threshold)

    # -- outputs ------------------------------------------------------------ #

    def diagnose(self, edge: EdgeMeta) -> SegmentDiagnosis:
        p = self.policy
        g = self.group_of(edge)
        observed = [b for b in range(BUCKET_COUNT) if (g, b) in self.traffic] or range(BUCKET_COUNT)
        peak_bucket = max(observed, key=lambda b: self.traffic.get((g, b), 0.0))
        peak = math.exp(max(0.0, self.traffic.get((g, peak_bucket), 0.0)))
        cf = self.condition_factor(edge.segment_id)
        w = self.weight.get(edge.segment_id, 0.0)
        if w < p.diagnose_min_weight:
            kind = SegmentKind.UNKNOWN
        else:
            bad_condition = cf < p.condition_kind_ratio
            heavy_traffic = peak >= p.traffic_kind_slowdown
            kind = (SegmentKind.BOTH if bad_condition and heavy_traffic else
                    SegmentKind.CONDITION if bad_condition else
                    SegmentKind.TRAFFIC if heavy_traffic else SegmentKind.NORMAL)
        return SegmentDiagnosis(edge.segment_id, kind, cf, peak, peak_bucket, w,
                                self.drivers.get(edge.segment_id, 0))

    def traffic_statements(self, bucket: int) -> list[Statement]:
        """Per-request speed rules for the departure bucket, one per road class.

        Only possible while groups are road classes; zone groups need area conditions.
        Clamped for routing (a floor on the multiplier) so a jammed class never looks
        unusable; the ETA path uses the unclamped speed_kmh().
        """
        if self.group_of is not default_group:
            return []
        rules = []
        for rc in RoadClass:
            slow = math.exp(max(0.0, self.group_traffic_log(rc.value, bucket)))
            if slow <= 1.0:
                continue
            factor = max(1.0 / slow, self.policy.min_routing_traffic_factor)
            rules.append(Statement(
                Target.SPEED, RoadClassIs(rc), Op.MULTIPLY_BY, round(factor, 3), Source.TELEMETRY_TRAFFIC,
                f"traffic.{rc.value.lower()}.{bucket}", reason=f"slowdown={slow:.2f}",
                active_buckets=frozenset({bucket})))
        return rules


def fit_speed_model(edges: dict[str, EdgeMeta], samples: Iterable[SpeedSample], now: datetime,
                    buckets: TimeBuckets,
                    group_of: Callable[[EdgeMeta], str] = default_group,
                    policy: SpeedModelPolicy = DEFAULT_SPEED_POLICY,
                    prior: CongestionPrior | None = DEFAULT_CONGESTION_PRIOR) -> FittedSpeedModel:
    window = timedelta(days=policy.window_days)
    kept = [s for s in samples
            if s.segment_id in edges and s.speed_kmh > 0 and timedelta(0) <= now - s.observed_at <= window]

    # A driver circling the same road counts once per hour of each day, however many pings.
    def vote_key(s: SpeedSample) -> tuple:
        return s.driver_id, s.segment_id, buckets.local_date(s.observed_at), buckets.of(s.observed_at)

    per_vote = Counter(vote_key(s) for s in kept)
    drivers: dict[str, set] = defaultdict(set)
    obs: list[_Obs] = []
    for s in kept:
        edge = edges[s.segment_id]
        r = min(policy.max_log, max(policy.min_log, math.log(edge.speed_kmh / s.speed_kmh)))
        age_days = (now - s.observed_at).total_seconds() / 86400.0
        w = 0.5 ** (age_days / policy.half_life_days)
        w /= per_vote[vote_key(s)]
        obs.append(_Obs(s.segment_id, group_of(edge), buckets.of(s.observed_at), r, w))
        drivers[s.segment_id].add(s.driver_id)

    model = FittedSpeedModel(buckets, group_of, policy, edges, prior=prior)
    c: dict[str, float] = {}
    t: dict[tuple[str, int], float] = {}
    u: dict[tuple[str, int], float] = {}

    def prior_target(gb: tuple[str, int]) -> float:
        return prior.log_slowdown(gb[0], gb[1]) if prior is not None else 0.0

    for _ in range(policy.iterations):
        raw_t = _shrunk_means(
            obs, key=lambda o: (o.group, o.bucket),
            residual=lambda o: o.r - c.get(o.seg, 0.0) - u.get((o.seg, o.bucket), 0.0),
            k=policy.traffic_prior_weight,
            target=prior_target)
        t = _anchor_quiet_hours(raw_t, policy)

        model.traffic = t
        c = {seg: v for seg, (v, _) in _shrunk_means(
            obs, key=lambda o: o.seg,
            residual=lambda o: o.r - model.group_traffic_log(o.group, o.bucket) - u.get((o.seg, o.bucket), 0.0),
            k=policy.condition_prior_weight, target=lambda _: 0.0).items()}
        u = {key: v for key, (v, _) in _shrunk_means(
            obs, key=lambda o: (o.seg, o.bucket),
            residual=lambda o: o.r - c.get(o.seg, 0.0) - model.group_traffic_log(o.group, o.bucket),
            k=policy.local_prior_weight, target=lambda _: 0.0).items()}

    weights: dict[str, float] = defaultdict(float)
    for o in obs:
        weights[o.seg] += o.w
    model.condition, model.local = c, u
    model.weight = dict(weights)
    model.drivers = {seg: len(ds) for seg, ds in drivers.items()}
    return model


def _anchor_quiet_hours(raw: dict[tuple[str, int], tuple[float, float]],
                        policy: SpeedModelPolicy) -> dict[tuple[str, int], float]:
    by_group: dict[str, list[float]] = defaultdict(list)
    for (g, _), (v, w) in raw.items():
        if w >= policy.min_quiet_bucket_weight:
            by_group[g].append(v)
    quiet = {g: sum(sorted(vs)[:policy.quiet_bucket_count]) / min(len(vs), policy.quiet_bucket_count)
             for g, vs in by_group.items()}
    return {(g, b): max(0.0, v - quiet.get(g, 0.0)) for (g, b), (v, _) in raw.items()}
