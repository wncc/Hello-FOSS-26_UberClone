"""Learn time-dependent junction delays from GPS-derived observations."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable

from .time_buckets import TimeBuckets


class DelayKind(str, Enum):
    SIGNAL = "signal"
    TURN = "turn"


@dataclass(frozen=True)
class DelayObservation:
    kind: DelayKind
    junction_id: str
    driver_id: str
    observed_at: datetime
    wait_s: float
    inbound_segment: str | None = None
    outbound_segment: str | None = None


@dataclass(frozen=True)
class DelayPolicy:
    half_life_days: float = 28.0
    window_days: float = 56.0
    prior_weight: float = 5.0
    min_drivers: int = 5
    min_days: int = 3
    min_weight: float = 10.0
    max_wait_s: float = 600.0


DEFAULT_DELAY_POLICY = DelayPolicy()


class FittedDelayModel:
    def __init__(
        self,
        buckets: TimeBuckets,
        policy: DelayPolicy,
        estimates: dict[tuple, float],
    ):
        self.buckets = buckets
        self.policy = policy
        self.estimates = estimates

    def signal_wait_s(
        self,
        junction_id: str,
        when: datetime,
        default_s: float = 30.0,
    ) -> float:
        key = (DelayKind.SIGNAL, junction_id, self.buckets.of(when))
        return self.estimates.get(key, default_s)

    def turn_wait_s(
        self,
        inbound_segment: str,
        outbound_segment: str,
        when: datetime,
        default_s: float,
    ) -> float:
        key = (
            DelayKind.TURN,
            inbound_segment,
            outbound_segment,
            self.buckets.of(when),
        )
        return self.estimates.get(key, default_s)


def fit_delay_model(
    observations: Iterable[DelayObservation],
    now: datetime,
    buckets: TimeBuckets,
    signal_default_s: float = 30.0,
    turn_defaults: dict[tuple[str, str], float] | None = None,
    policy: DelayPolicy = DEFAULT_DELAY_POLICY,
) -> FittedDelayModel:
    """Fit delays with vote caps, decay, shrinkage and evidence thresholds."""
    turn_defaults = turn_defaults or {}

    votes: dict[tuple, list[DelayObservation]] = defaultdict(list)

    for obs in observations:
        age = now - obs.observed_at
        if not timedelta(0) <= age <= timedelta(days=policy.window_days):
            continue
        if not math.isfinite(obs.wait_s) or obs.wait_s < 0:
            continue

        bucket = buckets.of(obs.observed_at)

        if obs.kind is DelayKind.SIGNAL:
            key = (DelayKind.SIGNAL, obs.junction_id, bucket)
        elif obs.kind is DelayKind.TURN:
            if not obs.inbound_segment or not obs.outbound_segment:
                continue
            key = (
                DelayKind.TURN,
                obs.inbound_segment,
                obs.outbound_segment,
                bucket,
            )
        else:
            continue

        # One driver gets one vote for this junction/turn per local hour.
        local = buckets.local(obs.observed_at)
        vote_key = (
            key,
            obs.driver_id,
            local.date(),
            local.hour,
        )
        votes[vote_key].append(obs)

    grouped: dict[tuple, list[tuple[float, float, str, object]]] = defaultdict(list)

    for vote_key, samples in votes.items():
        key, driver_id, day, _ = vote_key
        values = sorted(min(s.wait_s, policy.max_wait_s) for s in samples)
        median = values[len(values) // 2]

        newest = max(s.observed_at for s in samples)
        age_days = (now - newest).total_seconds() / 86400
        weight = 0.5 ** (age_days / policy.half_life_days)

        grouped[key].append((median, weight, driver_id, day))

    estimates = {}

    for key, rows in grouped.items():
        drivers = {row[2] for row in rows}
        days = {row[3] for row in rows}
        weight = sum(row[1] for row in rows)

        if (
            len(drivers) < policy.min_drivers
            or len(days) < policy.min_days
            or weight < policy.min_weight
        ):
            continue

        if key[0] is DelayKind.SIGNAL:
            default = signal_default_s
        else:
            default = turn_defaults.get((key[1], key[2]))
            if default is None:
                continue

        weighted_sum = sum(value * w for value, w, _, _ in rows)
        estimates[key] = (
            weighted_sum + policy.prior_weight * default
        ) / (weight + policy.prior_weight)

    return FittedDelayModel(buckets, policy, estimates)
