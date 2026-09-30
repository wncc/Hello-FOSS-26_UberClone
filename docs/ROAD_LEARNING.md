# Learning slower and avoided roads

This doc builds on [ROUTING.md](ROUTING.md). It covers how the router learns from driver telemetry:
1. which roads are **slower than expected**, and whether that slowness is **traffic** (depends on the time of week) or **road condition** (permanent);
2. which roads drivers **avoid**, without mistaking rush-hour avoidance for a bad road.

**Starting assumption:** every road has the same expected speed, `UNIFORM_SPEED_KMH` = 30 km/h, capped at its legal limit ([MAP_DATA.md](MAP_DATA.md)). Any slowness beyond that comes only from data. Initial ETA approximation (per-class speeds, a starting congestion table, calibration) is postponed: see [issue 001](issues/001-eta-approximation.md).
Out of scope: yearly and festival patterns, and live incident traffic.

---

## 1. Slower roads: traffic vs. condition

### Model ([routing/speed_model.py](../routing/speed_model.py))

For every observed traversal, on a log scale (so effects multiply, like the cost formula):

```
r = ln(expected_speed / observed_speed) = c[segment] + t[group, bucket] + u[segment, bucket] + noise
```

| Term | Meaning | Example |
|---|---|---|
| `c[s]` **condition** | Slow even when the road is empty. Permanent | Potholes, speed breakers, bad surface, narrow lane |
| `t[g, b]` **shared traffic** | How much slower the group (road class; later road class × zone) gets in time bucket b, ≥ 0 | Weekday 09:00 on primary roads: 2× |
| `u[s, b]` **local traffic** | This segment's own extra slowdown at certain hours | A school gate at 08:00, a market street in the evening |

**Time buckets** ([routing/time_buckets.py](../routing/time_buckets.py)): weekday / Saturday / Sunday × 24 hours = 72 buckets, in the **city's local time zone** (`TimeBuckets(IST)`). That's deliberately coarse, so each bucket fills with data about 28× faster than a 7 × 288 five-minute grid. Split weekdays apart later.

**How the two are told apart:** each group's quietest well-observed hours are defined as zero traffic. So:
- **Condition** = slowness that is still there at the quietest time of the week. A road that's slow at 3 a.m. isn't slow because of traffic.
- **Traffic** = everything on top of that which follows the clock, shared across similar roads.

Comparing a segment with its peers gives a second check. If it's slow in the same hours as every other primary road, that's traffic (`t`). If it's slow at all hours, that's condition (`c`). If it's slow only when its peers aren't, that's local (`u`).

**Fitting:** alternating shrunk means (backfitting). Each term is the weighted mean of what the other terms leave unexplained, pulled toward 0 ("as expected"):
- `t` with k = 20
- `c` with k = 10
- `u` with k = 30, because a segment-specific pattern needs a lot of evidence

Sparse segments borrow strength from their group instead of overfitting.

**Weighting:** exponential decay (28-day half-life, 8-week window), and **one vote per driver per segment per hour per day**. A driver circling one road doesn't outvote everyone else.

**Validation on synthetic data** ([tests/test_traffic.py](../tests/test_traffic.py); true values in brackets):
- Condition of a bad primary road: 0.60 (0.60). Of a bad residential road: 0.52 (0.50).
- Primary-road slowdown: weekday 09:00 1.89 (2.0), 14:00 1.26 (1.3), 02:00 1.00 (1.0).
- `diagnose()` classifies the four test roads as TRAFFIC / BOTH / NORMAL / CONDITION, all correctly.

The small underestimate at peaks is the deliberate pull toward "as expected".

### What each part feeds

| Output | Used by | How |
|---|---|---|
| `c` (condition) | Routing, permanent | Speed samples are divided by the learned traffic before they reach the existing guarded pipeline (`aggregate(..., traffic=model)`). Evidence tiers, the hierarchy floor, hysteresis and expiry all still apply. So a speed rule means "bad road", never "busy road" |
| `t` (shared traffic) | Routing, per request | `traffic_statements(bucket)` adds one `speed multiply_by` per road class for the departure time. Capped at ×0.4 so a jammed road class never looks unusable |
| `c + t + u` | ETA | `speed_kmh(edge, time)` and `route_eta_s()`, which advances the clock along the route. **Never capped**: ETA must be honest even when routing is protected |
| `diagnose()` | Analytics / ops | NORMAL / CONDITION / TRAFFIC / BOTH / UNKNOWN per segment. CONDITION segments are the list to send to civic bodies |

**Why this matters:** ride-hailing demand is concentrated at peak hours, so most observations of a busy main road come from rush hour. Taking a median over all hours would conclude that the road is permanently bad and penalize it all day. The `test_rush_hour_skew_no_longer_looks_like_bad_road` test shows the plain median producing that false rule, the de-trended version producing none, and the genuinely bad road still being caught.

### Alternatives considered
- **[Valhalla](https://valhalla.github.io/valhalla/mjolnir/historical_traffic/) historical traffic.** Stores a full week of speeds per edge in 5-minute buckets (compressed) and routes with true time-dependent speeds. Worth switching engines to if time-dependent route choice becomes important. `speed_kmh(edge, time)` can produce its input.
- **[OSRM](https://github.com/Project-OSRM/osrm-backend/wiki/Traffic) with the MLD algorithm.** Speeds can be updated from a CSV without a full rebuild, typically one dataset per time bucket. You lose GraphHopper's per-request custom model.
- **Deep models** (Uber DeepETA; Google/DeepMind graph neural networks). They need far more trips than we have. The statistical model above is the baseline they must beat.

---

## 2. Avoided roads

**Base mechanism:** each planned segment the driver reached counts as one "exposure", with an outcome of followed or deviated (`detect_exposures`). The avoidance rate uses a Beta prior, plus evidence tiers (distinct drivers, distinct days), hysteresis and expiry.

**Separating rush-hour avoidance from permanent avoidance.** Exposures in the segment's learned peak buckets (slowdown ≥ 1.3) are counted separately:
- **Off-peak avoidance** → a **permanent** priority rule (`tele.dev.<segment>`).
- **Peak-only avoidance** → a rule that applies **only at peak hours** (`tele.dev.peak.<segment>`, with `active_buckets` set). It's included only when the departure time falls in those buckets. If both rules exist, the stricter one wins; they never compound.

Why not let the speed model handle rush-hour avoidance? It's circular: if drivers avoid a jammed road, we get no speed samples from it, so the speed model never learns it's jammed. Avoidance is the only signal we have for that road.

**Suspected map errors.** A segment with strong evidence of avoidance (rate ≥ 0.8) and **no speed samples from anyone** probably doesn't exist as mapped: a gate, a missing turn restriction, a closed road. It's flagged in `RoadHealth.suspected_map_error` for a map-fix queue, and it still gets the 0.01 priority.

**Next steps (designed, not built):**

| Idea | Why | Needs |
|---|---|---|
| **Outcome-aware deviations** | A driver who deviated and arrived *earlier* than our ETA for the rest of the planned route probably knew a faster road. That's a speed signal, not avoidance. Arriving later means the road was avoided for another reason (condition, safety, preference) | Our ETA for the remaining planned route at the deviation point, plus the actual time for that part of the trip |
| **Turn-level avoidance** | Drivers often avoid a *turn* (a right turn across traffic, a U-turn), not the whole road | Exposures keyed by (entry segment, exit segment). GraphHopper turn costs |
| **Priors per road class, fitted from data** (empirical Bayes) | Background avoidance differs by class | Fit Beta(a, b) per class from population data |
| **Voluntary-use counter-signal** | Drivers choosing an unplanned road is evidence against penalizing it | Count traversals that weren't on the plan |
| **Driver reliability weights** | New drivers and drivers who don't know the city add noise | Weight by driver tenure |

---

## 3. Data needed from the telemetry / trips team

| Event | Fields | Notes |
|---|---|---|
| `SpeedSample` (one per full map-matched traversal) | segment_id, driver_id, trip_id, speed_kmh = segment length / traversal time, observed_at (UTC, timezone-aware) | **Leave out** partially driven first and last segments and time stopped at a pickup or drop-off. Include idle-to-pickup driving too: more coverage, same physics |
| `SegmentExposure` | planned vs. actual segment lists → `detect_exposures()` | After a reroute, send the new plan as a new call |

## 4. Usage

```python
from routing import RoutingService, LocalAStarRouter, RoadGraph, TimeBuckets, IST

svc = RoutingService(backend, edges, buckets=TimeBuckets(IST))   # edges built without speed_kmh
svc.refresh_telemetry(speed_samples, exposures)                  # every ~15 min
route = svc.route(start, end, depart_at=pickup_time)             # traffic rules + ETA for that time
svc.speed_model.diagnose(edges[seg])                             # CONDITION / TRAFFIC / BOTH / ...
svc.health[seg].suspected_map_error
```

## 5. Limitations

- **Route choice uses one time bucket.** Routing applies the departure bucket to the whole trip, while the ETA does propagate the clock.
- **Segment-specific traffic (`u`) isn't used in routing yet.** It feeds only the ETA, because per-segment, per-bucket rules are expensive to send in each GraphHopper request.
- **Slow recovery after repairs.** Condition changes are tracked only through the 28-day decay. Change-point detection on quiet-hour observations would react within days.
- **Traffic groups are city-wide road classes.** A primary road in the centre and one on the outskirts share a single traffic profile until zones are added.
- **GraphHopper speed setting needs checking.** Uniform speed on the server relies on `{"if": "true", "limit_to": "30"}` setting every road to 30 km/h. Confirm this on the deployed GraphHopper version, or use `car_average_speed` once [issue 001](issues/001-eta-approximation.md) is done.
