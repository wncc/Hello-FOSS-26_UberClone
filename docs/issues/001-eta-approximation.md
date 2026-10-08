# Issue 001: ETA approximation before we have our own data

**Status:** open, postponed · **Labels:** eta, routing, enhancement
**Blocked by:** nothing. Postponed on purpose, so we can build learning of slow and avoided roads first.

## Context

Routing currently assumes **every road has the same speed** (`UNIFORM_SPEED_KMH` = 30 km/h, [routing/road_classes.py](../../routing/road_classes.py)), capped at the legal limit. Legal limits are already extracted for every road ([MAP_DATA.md](../MAP_DATA.md)): signs where mapped, national defaults otherwise. Use them as an upper bound for per-road speeds. Slower roads are learned only from telemetry ([docs/ROAD_LEARNING.md](../ROAD_LEARNING.md)). Until enough telemetry exists, ETAs are just `distance / 30 km/h`, which is wrong on fast arterials and at rush hour.

This issue covers the **initial ETA approximation**: how to estimate ETAs with little or no data of our own.

## Options found

| Option | Traffic-aware | Cost | Notes |
|---|---|---|---|
| Routing engine free-flow time (GraphHopper `car_average_speed`; OSRM and Valhalla are similar) | No | Free | Optimistic at peak hours; good base |
| [Google Routes API](https://developers.google.com/maps/documentation/routes) `TRAFFIC_AWARE` / `TRAFFIC_AWARE_OPTIMAL` | Yes | Traffic-aware requests use the more expensive pricing tier ([billing](https://developers.google.com/maps/documentation/routes/usage-and-billing)). Route matrices are capped at 100 elements per request with `TRAFFIC_AWARE_OPTIMAL` | Very accurate. Too expensive to call for every dispatch comparison |
| Mapbox `driving-traffic`, TomTom, HERE, Mappls, Ola Maps | Yes | Paid | Pricing and terms not yet checked |

## Proposed design

1. **Per-class or map speeds instead of one uniform speed.** Switch `baseline_model()` to `limit_to car_average_speed` (the constant `EDGE_AVERAGE_SPEED` is kept for this). Build `EdgeMeta.speed_kmh` from the same map value. `RoutingService` already refuses edges whose speeds disagree with the baseline.
2. **A starting congestion table** (road class × weekday/Saturday/Sunday × hour, as a slowdown multiplier). Proposed starting values for a large Indian city, **all guesses**:

   | Hours (weekday) | Main roads | Minor roads |
   |---|---|---|
   | 00–05 | 1.0 | 1.0 |
   | 06–07 | 1.15 | 1.1 |
   | 08–10 | 1.8 | 1.4 |
   | 11–16 | 1.4 | 1.2 |
   | 17–20 | 2.0 | 1.5 |
   | 21–23 | 1.2 | 1.1 |

   Saturday: 0.8 × the weekday excess over 1.0. Sunday: 0.5 ×. The speed model's traffic term can then start from `ln(slowdown)` instead of 0, so learned data replaces the table gradually as it arrives.
3. **Calibration.** Keep a per-time-bucket correction factor, learned from (predicted, actual) pairs:
   `factor[b] = exp((Σ log(actual/predicted) + k·global) / (n_b + k))`, with k = 20 and each log ratio clipped to ±ln 3.
   - Before real trips exist, the pairs can come from a reference API on 1–5% of trips.
   - ⚠ **First check the provider's terms.** Google Maps Platform restricts storing its content and using it alongside non-Google maps. If calibration isn't allowed, use actual trip durations instead.
4. **Trip-level residual model.** Later, replace the calibration factor with a learned model of the gap between the routing ETA and actual trip time, in the spirit of Uber's [DeepETA](https://www.uber.com/in/en/blog/deepeta-how-uber-predicts-arrival-times/) / [DeeprETA](https://ar5iv.labs.arxiv.org/html/2206.02127).

A prototype of steps 2 and 3 (`CongestionPrior`, `EtaCalibrator`) was written and tested during design but not committed. The formulas above are enough to rebuild it.

## Acceptance criteria

- [ ] ETA at weekday 09:00 is longer than at 03:00 for the same route before any telemetry exists.
- [ ] The starting table is scaled by per-bucket calibration factors, and median absolute % ETA error per bucket is tracked.
- [ ] The speed model shrinks toward the starting table rather than toward 0, and the existing learning tests still pass.
- [ ] Provider terms are reviewed before any reference-API data is stored.
