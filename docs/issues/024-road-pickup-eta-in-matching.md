# Issue 024: Road-based pickup times in matching (fast enough for every cycle)

**Difficulty:** 🔴 hard · **Area:** routing + matching · **Skills:** algorithms (Dijkstra / A*), Python performance

## Why
Matching chooses which drivers to ping using **straight-line distance × 1.4**. A driver across a creek or a railway line looks close but may be 20 minutes away by road. The road router exists, but running one route per driver (up to 10 drivers per rider, every 3 seconds) is too slow in Python today (0.1–1 s per route).

## What to do
- Compute times from **all** nearby drivers to a rider in one search: a single reverse Dijkstra outward from the pickup, stopping at a time limit (e.g. 15 minutes), reading off the time for each driver's node. That's one search instead of N.
- Optional speed-ups: cache by (pickup cell, minute), limit the search area, or build a contracted graph.
- Plug it into matching as an `EtaProvider`, and make `RouteService.pickup_eta` use it when road data is loaded.

## Where to look
- `matching/eta.py`: the `EtaProvider` protocol, `StraightLineEta`, `RouterEta`.
- `backend/app/services/routes.py`: `pickup_eta` (straight line today, and why).
- `routing/engine.py`: `LocalAStarRouter` (edge-based search with turn costs; the one-to-many version needs the same cost model).
- `matching/engine.py`: `MatchingConfig.eta_candidates`, `max_pickup_eta_s`.

## Done when
- [ ] Times to 10 drivers within 4 km in Mumbai take under 200 ms in total (include a benchmark script).
- [ ] The results match single routes (`LocalAStarRouter.route`) within a few seconds (test).
- [ ] A driver across a barrier with no direct road isn't chosen over a driver who is truly closer by road (test, like `tests/test_matching.py::RoutingIntegrationTests`).
