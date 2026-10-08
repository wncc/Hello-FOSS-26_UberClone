# routing/

The routing engine: **finds routes on real roads and estimates time and distance**, with Indian road rules, per-vehicle behaviour, and learning from driver GPS. Start with [docs/OVERVIEW.md](../docs/OVERVIEW.md#how-a-route-is-chosen), then [docs/ROUTING.md](../docs/ROUTING.md).

| File | What it is | Docs |
|---|---|---|
| `models.py` | Road segments (`EdgeMeta`), telemetry events, rule statements, zones, results | [ROUTING.md](../docs/ROUTING.md) |
| `road_classes.py` | Road hierarchy (priority per road class) and the uniform expected speed | [ROUTING.md](../docs/ROUTING.md) |
| `vehicles.py` | Car / auto / bike profiles: legal limits, access keys, tolls, turn costs, waits at signals and tolls | [VEHICLES_AND_TURNS.md](../docs/VEHICLES_AND_TURNS.md) |
| `rule_engine.py` | Baseline model, rule validation and merging, per-segment evaluation | [ROUTING.md](../docs/ROUTING.md) |
| `restrictions.py` | Access rules, time-based closures, restricted zones, avoid-tolls option | [MAP_DATA.md](../docs/MAP_DATA.md) |
| `turns.py` | Turn classification (left-hand traffic), turn costs, turn restrictions | [VEHICLES_AND_TURNS.md](../docs/VEHICLES_AND_TURNS.md) |
| `graph.py` | Road graph, snapping points to the nearest usable road in the main network | [MAP_DATA.md](../docs/MAP_DATA.md) |
| `engine.py` | `LocalAStarRouter` (edge-based A*), `RoutingService` (one vehicle), `MultiVehicleRouter` | [ROUTING.md](../docs/ROUTING.md) |
| `cost.py` | The cost formula, ETA along a route, removing point waits from telemetry | [ROUTING.md](../docs/ROUTING.md) |
| `telemetry.py` | Turning speed samples and avoidance into guarded rules | [ROAD_LEARNING.md](../docs/ROAD_LEARNING.md) |
| `speed_model.py` | Separating time-of-week traffic from permanent road condition | [ROAD_LEARNING.md](../docs/ROAD_LEARNING.md) |
| `time_buckets.py` | Weekday / Saturday / Sunday × hour buckets in IST | [ROAD_LEARNING.md](../docs/ROAD_LEARNING.md) |
| `monitoring.py` | Detecting where drivers left the planned route; route-quality records | [ROAD_LEARNING.md](../docs/ROAD_LEARNING.md) |
| `osm_import.py` | Building road data from OpenStreetMap (`python -m routing.osm_import`) | [MAP_DATA.md](../docs/MAP_DATA.md) |
| `graphhopper.py` | Converting the model to GraphHopper and calling its API | [VEHICLES_AND_TURNS.md](../docs/VEHICLES_AND_TURNS.md) |

Tests: `tests/test_routing.py`, `test_restrictions.py`, `test_vehicles_turns.py`, `test_traffic.py`, `test_graph.py`.
