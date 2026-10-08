# Issue 002: GraphHopper import plugin for vehicles, point delays and speed breakers

**Status:** open · **Labels:** graphhopper, routing, vehicles

## Context

The local engine ([routing/engine.py](../../routing/engine.py)) models vehicles, turns, point delays and speed breakers ([VEHICLES_AND_TURNS.md](../VEHICLES_AND_TURNS.md)). Stock GraphHopper 11 covers turn penalties by angle, U-turn costs and OSM turn restrictions. The rest needs custom encoded values, set by tag parsers at import (Java; see GraphHopper's `TagParser` / `EncodedValue` extension points).

## Work

1. **Access per vehicle.** Add `motorcycle_access` (from `motorcycle` → `motor_vehicle` → `vehicle` → `access`) and `auto_access` (the stricter of car and motorcycle). Three-wheelers are barred from `highway=motorway`. Use them in `bike.json` / `auto_rickshaw.json` in place of `!car_access`.
2. **Legal speed limits per vehicle.** Add `motorcycle_max_speed` and `auto_max_speed`, following `osm_import.maxspeed_for` with a general sign capped at the category maximum. Replace `limit_to max_speed` in those profiles.
3. **Speed breakers.** Add a directional boolean `traffic_calming`: true when the way is calmed or the segment ends at a calming node. Then `{"if": "traffic_calming", "multiply_by": 0.9}` (emitted with `extensions=True`).
4. **Point delays.** Add directional booleans `signal_ahead`, `toll_booth_ahead` and `level_crossing_ahead` on the edge that arrives at the feature node, respecting `traffic_signals:direction`.
   - **Catch:** GraphHopper merges OSM node-to-node segments into longer edges between junctions, and `turn_penalty` fires only at an edge boundary. A signal at a junction works. A mid-block signal, toll booth or level crossing gets no transition. Either split edges at feature nodes on import (GraphHopper already splits at barriers), or add the delay to the edge weight in a custom weighting.
5. **Verify the sign of `change_angle`** (positive = right turn?) and set `GH_RIGHT_TURN_IS_POSITIVE` in [graphhopper.py](../../routing/graphhopper.py).
6. **Check `turn_costs.vehicle_types`** for the auto profile (`[motorcar, motorcycle, motor_vehicle]`): it should apply a restriction for *any* listed type.

## Acceptance criteria

- [ ] For the same OSM extract, GraphHopper and the local engine choose the same route on a set of replayed trips per vehicle, with any differences explained.
- [ ] `write_server_models(dir, extensions=True)` output loads in GraphHopper without errors.
- [ ] A mid-block signal adds its delay in GraphHopper's route time.
