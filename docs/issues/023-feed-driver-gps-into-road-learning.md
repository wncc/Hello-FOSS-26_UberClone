# Issue 023: Feed real driver GPS into road learning (slow and avoided roads)

**Difficulty:** 🔴 hard (high impact) · **Area:** backend + routing · **Skills:** Python, geometry / map matching, data pipelines

## Why
The routing engine can learn which roads are slow (separating traffic from road condition) and which roads drivers avoid (see `docs/ROAD_LEARNING.md`). The backend also stores every driver GPS point (the `LocationPing` table). **But nothing connects the two**: `refresh_telemetry` is never called with real data, so the learning never runs.

## What to do
1. **Store the planned route.** When a ride is assigned and when the trip starts, save the planned list of road segment IDs for the approach and the trip (for `detect_exposures`).
2. **Map matching:** turn each driver's GPS breadcrumbs into the sequence of road segments actually driven, with the time spent on each. A simple approach works for a first version:
   - snap points to nearby segments;
   - connect consecutive snapped segments with a shortest path;
   - discard noisy points.
   An HMM matcher (as in GraphHopper Map Matching or Valhalla Meili) is the better long-term option.
3. **Produce the inputs the learning engine expects:**
   - `SpeedSample(segment_id, driver_id, trip_id, speed_kmh, observed_at, vehicle)` for each fully driven segment. Leave out the first and last partial segments, and time spent waiting at pickup.
   - `SegmentExposure` from planned vs actual, via `routing.monitoring.detect_exposures`.
4. **Run a scheduled job** (e.g. every 15 minutes) that collects recent samples per vehicle and calls `MultiVehicleRouter.refresh_telemetry`. Log what was learned (how many speed rules, avoidance rules, suspected map errors).

## Where to look
- `backend/app/models.py`: `LocationPing`. `backend/app/services/locations.py` stores it.
- `routing/models.py`: `SpeedSample`, `SegmentExposure`. `routing/monitoring.py`: `detect_exposures`.
- `routing/engine.py`: `RoutingService.refresh_telemetry`, `MultiVehicleRouter.refresh_telemetry`.
- `backend/app/services/routes.py`: `RouteService.router` (the loaded road network).
- `docs/ROAD_LEARNING.md`: what the learning does with these inputs.

## Done when
- [ ] A test feeds a synthetic GPS trace along known roads and gets the right segment sequence and speeds.
- [ ] After simulated rides (e.g. `demo.py`), the job runs and road-health data appears for the driven segments.
- [ ] A short explanation of the matching approach and its limits is added to `docs/ROAD_LEARNING.md`.
