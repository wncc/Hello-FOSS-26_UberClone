"""Ride matching: broadcast pings to nearby free drivers, nearest acceptance wins.

Port of ride-matching-engine-uber-main/matchingServer.js, with the same /state
contract and statuses, plus fixes and routing integration:

  * drivers are only pinged for riders who requested their vehicle type
  * "nearest" means shortest pickup ETA on the road network when an EtaProvider
    is given (straight-line distance otherwise)
  * an already-confirmed match is never reassigned to a later acceptor
  * other drivers pinged for a matched rider are released
  * unanswered pings time out; riders whose pinged drivers all rejected or timed
    out go back to ping_pending
  * drivers whose rider vanished (cancelled) are released
  * records with missing / non-numeric coordinates or unknown vehicles are
    skipped instead of failing the whole cycle

Statuses:
  driver: free -> pinged (one rider) -> accepted | back to free
  rider:  ping_pending -> driver_pinged (driverIds) -> accepted (driverId)
The engine never accepts or rejects on a driver's behalf; the backend does that.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from routing import VehicleType

from .eta import EtaProvider
from .geo import GridIndex, LatLng, haversine_km

Record = dict[str, Any]

FREE, PINGED, ACCEPTED = "free", "pinged", "accepted"
PING_PENDING, DRIVER_PINGED = "ping_pending", "driver_pinged"


@dataclass(frozen=True)
class MatchingConfig:
    radius_km: float = 4.0               # straight-line ping radius (cheap prefilter)
    reserve_ratio: float = 0.2           # free drivers held back each cycle
    max_drivers_per_rider: int = 3       # broadcast fan-out
    ping_timeout_s: float = 20.0         # unanswered ping -> driver freed
    max_pickup_eta_s: float | None = 15 * 60  # with an EtaProvider: skip drivers farther than this
    eta_candidates: int = 10             # route at most this many nearest drivers per rider
    selection: str = "random"            # "random" spreads pings fairly (original); "nearest" = lowest ETA


@dataclass
class CycleResult:
    state: dict[str, list[Record]]
    accepted: list[dict[str, str]]
    stats: dict[str, int] = field(default_factory=dict)


def _position(rec: Record) -> LatLng | None:
    lat, lng = rec.get("lat"), rec.get("lng")
    if isinstance(lat, bool) or isinstance(lng, bool) or not isinstance(lat, (int, float)) \
            or not isinstance(lng, (int, float)) or not (math.isfinite(lat) and math.isfinite(lng)):
        return None
    return float(lat), float(lng)


def _vehicle(rec: Record) -> VehicleType | None:
    try:
        return VehicleType(rec.get("vehicle") or VehicleType.CAR.value)
    except ValueError:
        return None


def _valid(rec: Record) -> bool:
    return bool(rec.get("id")) and _position(rec) is not None and _vehicle(rec) is not None


def _now_ms(now: datetime) -> int:
    return int(now.timestamp() * 1000)


def _free(driver: Record) -> None:
    driver["status"] = FREE
    driver["riderId"] = None
    driver["pingedAt"] = None


def _pickup_cost(driver: Record, rider: Record, eta: EtaProvider | None, now: datetime) -> float:
    """Seconds when an EtaProvider is available, else km; only compared within one rider."""
    if eta is None:
        return haversine_km(_position(driver), _position(rider))
    seconds = eta.pickup_eta_s(_position(driver), _position(rider), _vehicle(rider), now)
    return math.inf if seconds is None else seconds


def resolve_accepted_conflicts(drivers: dict[str, Record], riders: dict[str, Record],
                               eta: EtaProvider | None, now: datetime, stats: dict[str, int]) -> None:
    accepted_by_rider: dict[str, list[Record]] = {}
    for d in drivers.values():
        if d.get("status") == ACCEPTED and d.get("riderId"):
            accepted_by_rider.setdefault(d["riderId"], []).append(d)

    for rider_id, candidates in accepted_by_rider.items():
        rider = riders.get(rider_id)
        if rider is None:
            for d in candidates:
                _free(d)
            stats["drivers_released_cancelled"] = stats.get("drivers_released_cancelled", 0) + len(candidates)
            continue

        locked = next((d for d in candidates
                       if rider.get("status") == ACCEPTED and rider.get("driverId") == d["id"]), None)
        winner = locked or min(candidates, key=lambda d: (_pickup_cost(d, rider, eta, now), d["id"]))
        for d in candidates:
            if d is not winner:
                _free(d)
        winner["pingedAt"] = None
        rider["status"] = ACCEPTED
        rider["driverId"] = winner["id"]
        rider["driverIds"] = []


def release_stale(drivers: dict[str, Record], riders: dict[str, Record], now: datetime,
                  config: MatchingConfig, stats: dict[str, int]) -> None:
    now_ms = _now_ms(now)
    for d in drivers.values():
        if d.get("status") != PINGED:
            continue
        rider = riders.get(d.get("riderId"))
        if rider is None or rider.get("status") == ACCEPTED:
            _free(d)                                     # rider cancelled, or matched to someone else
            stats["drivers_released_matched"] = stats.get("drivers_released_matched", 0) + 1
        elif not isinstance(d.get("pingedAt"), (int, float)):
            d["pingedAt"] = now_ms                        # pinged before timestamps existed: start the clock
        elif now_ms - d["pingedAt"] > config.ping_timeout_s * 1000:
            _free(d)
            stats["pings_timed_out"] = stats.get("pings_timed_out", 0) + 1

    for r in riders.values():
        if r.get("status") == ACCEPTED and drivers.get(r.get("driverId"), {}).get("status") == FREE:
            r["status"], r["driverId"], r["driverIds"] = PING_PENDING, None, []   # matched driver cancelled
            stats["riders_requeued"] = stats.get("riders_requeued", 0) + 1
            continue
        if r.get("status") != DRIVER_PINGED:
            continue
        live = [i for i in r.get("driverIds") or []
                if drivers.get(i, {}).get("status") == PINGED and drivers[i].get("riderId") == r["id"]]
        r["driverIds"] = live
        if not live:
            r["status"] = PING_PENDING                    # everyone rejected or timed out: ping again
            stats["riders_repinged"] = stats.get("riders_repinged", 0) + 1


def assign_pings(drivers: dict[str, Record], riders: dict[str, Record], eta: EtaProvider | None,
                 now: datetime, config: MatchingConfig, rng: random.Random, stats: dict[str, int]) -> None:
    free = [d for d in drivers.values() if d.get("status") == FREE]
    index = GridIndex()
    for d in free:
        index.add(d["id"], _position(d))

    shuffled = free[:]
    rng.shuffle(shuffled)
    reserve = math.floor(len(shuffled) * config.reserve_ratio)
    usable = {d["id"] for d in shuffled[:len(shuffled) - reserve]}

    pending = [r for r in riders.values() if r.get("status") == PING_PENDING]
    rng.shuffle(pending)
    now_ms = _now_ms(now)

    for rider in pending:
        if not usable:
            break
        vehicle = _vehicle(rider)
        excluded = set(rider.get("excludedDriverIds") or ())   # e.g. drivers who already rejected this ride
        nearby = [(i, km) for i, km in index.within(_position(rider), config.radius_km)
                  if i in usable and i not in excluded and _vehicle(drivers[i]) is vehicle]
        if eta is not None:
            nearby = nearby[:config.eta_candidates]
            costed = [(i, eta.pickup_eta_s(_position(drivers[i]), _position(rider), vehicle, now)) for i, _ in nearby]
            nearby = [(i, s) for i, s in costed if s is not None
                      and (config.max_pickup_eta_s is None or s <= config.max_pickup_eta_s)]
        if not nearby:
            stats["riders_without_driver"] = stats.get("riders_without_driver", 0) + 1
            continue

        if config.selection == "nearest":
            chosen = [i for i, _ in sorted(nearby, key=lambda c: (c[1], c[0]))[:config.max_drivers_per_rider]]
        else:
            ids = [i for i, _ in nearby]
            rng.shuffle(ids)
            chosen = ids[:config.max_drivers_per_rider]

        for driver_id in chosen:
            d = drivers[driver_id]
            d["status"], d["riderId"], d["pingedAt"] = PINGED, rider["id"], now_ms
            usable.discard(driver_id)
        rider["status"] = DRIVER_PINGED
        rider["driverIds"] = chosen


def run_cycle(state: dict[str, list[Record]], now: datetime, eta: EtaProvider | None = None,
              config: MatchingConfig = MatchingConfig(), rng: random.Random | None = None) -> CycleResult:
    """One matching cycle on a /state payload. Mutates and returns the same records."""
    if config.selection not in ("random", "nearest"):
        raise ValueError(f"unknown selection {config.selection!r}")
    rng = rng or random.Random()
    stats: dict[str, int] = {}
    all_drivers, all_riders = state.get("drivers") or [], state.get("riders") or []
    drivers = {d["id"]: d for d in all_drivers if _valid(d)}
    riders = {r["id"]: r for r in all_riders if _valid(r)}
    stats["invalid_records"] = len(all_drivers) - len(drivers) + len(all_riders) - len(riders)

    resolve_accepted_conflicts(drivers, riders, eta, now, stats)
    release_stale(drivers, riders, now, config, stats)
    assign_pings(drivers, riders, eta, now, config, rng, stats)

    accepted = [{"riderId": r["id"], "driverId": r["driverId"]} for r in riders.values() if r.get("status") == ACCEPTED]
    stats.update(
        accepted=len(accepted),
        pinged_riders=sum(r.get("status") == DRIVER_PINGED for r in riders.values()),
        free_drivers=sum(d.get("status") == FREE for d in drivers.values()),
    )
    return CycleResult(state, accepted, stats)
