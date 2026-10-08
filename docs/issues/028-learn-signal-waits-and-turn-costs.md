# Issue 028: Learn traffic-signal waits and turn costs from real trips

**Difficulty:** 🔴 hard · **Area:** routing · **Skills:** Python, statistics

## Why
The router adds a fixed 30-second wait at every traffic signal, and fixed costs for left turns, right turns and U-turns. These are educated guesses (marked `ASSUMPTION` in the code). Real signals differ a lot, and right turns at some Mumbai junctions take minutes at rush hour.

## What to do
- Using map-matched trips (from issue 023), measure for each signal node (and for each turn at a junction) how long drivers actually wait, per time-of-week bucket.
- Learn it the same way the speed model learns traffic:
  - shrink sparse data toward the default;
  - count one vote per driver per hour;
  - require evidence from several drivers and days before trusting a value.
- Use the learned values in routing and ETAs, falling back to the defaults where there isn't enough data.

## Where to look
- `routing/vehicles.py`: `point_delay_s`, `TurnCosts` (the defaults).
- `routing/cost.py`: `moving_speed_kmh` (removes the expected wait from speed samples), `route_time_breakdown`.
- `routing/speed_model.py`: the pattern to follow (shrinkage, buckets, vote capping).
- `docs/VEHICLES_AND_TURNS.md`.

## Done when
- [ ] Tests with synthetic trips: a signal with 90-second waits at 6 pm and 10-second waits at 3 am is learned as such; a signal with only 2 observations stays near the default.
- [ ] Routing uses the learned waits, and still passes the existing tests.
