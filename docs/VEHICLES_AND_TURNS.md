# Vehicles, turns and point delays

This doc builds on [ROUTING.md](ROUTING.md), [MAP_DATA.md](MAP_DATA.md) and [ROAD_LEARNING.md](ROAD_LEARNING.md). The cost of a route is now:

```
Σ over segments   distance / (speed × priority)          ← the road itself
+ Σ over nodes     fixed wait at signals / tolls / crossings  ← point delays (seconds)
+ Σ over turns     turn cost, or ∞ if the turn is banned      ← turns (seconds)
```

Point delays and turn costs are **plain seconds**. They are never multiplied by the road's priority, and they never lower it. A road with a traffic light is still exactly as preferred as before; the trip just takes 30 s longer.

---

## 1. Vehicle profiles ([routing/vehicles.py](../routing/vehicles.py))

| | Car | Bike (motorcycle / scooter) | Auto rickshaw |
|---|---|---|---|
| **Legal max** (S.O. 1522(E), 2018): expressway / divided highway / other | 120 / 100 / 70 | 80 / 80 / 60 | not permitted / 50 / 50 |
| **Posted signs** | Followed as posted | Capped at the category max | Capped at the category max (an auto stays at 50 on an 80 road) |
| **OSM access keys** | `motorcar` → `motor_vehicle` → `vehicle` → `access` | `motorcycle` → … | Stricter of the car and motorcycle rules (OSM has no widely used auto-rickshaw key) |
| **Expressways** | Allowed | Allowed unless tagged `motorcycle=no` (several expressways ban two-wheelers) | **Blocked** |
| **Tolls** | Pays (`toll=yes`, `toll:motorcar`) | Exempt at NHAI plazas unless `toll:motorcycle=yes` | Treated as exempt (**verify** for state tolls) |
| **Residential priority** | 0.5 | 0.7 (filters through small lanes) | 0.6 |
| **Turn costs** (s): left / right / U-turn | 3 / 10 / 25 | 2 / 6 / 12 | 2 / 8 / 18 |
| **Point delays** (s): signal / toll booth / level crossing | 30 / 20 / 60 | 30 / 5 / 60 | 30 / 10 / 60 |

**Expected speed** stays uniform for now: `min(30 km/h, the vehicle's legal limit)`, × 0.9 where there is a speed breaker. Differences between vehicles come from access, legal limits, priorities, turns, delays, and later from **telemetry, which is learned separately per vehicle**. `SpeedSample` and `SegmentExposure` carry a `vehicle` field, and each vehicle's `RoutingService` only sees its own events.

```python
from routing import MultiVehicleRouter, TimeBuckets, IST, VehicleType
from routing.osm_import import load

router = MultiVehicleRouter.local(load("roads.json"), buckets=TimeBuckets(IST))   # or build with GraphHopper backends
router.refresh_telemetry(speed_samples, exposures)            # split by sample.vehicle
router.route(VehicleType.AUTO, pickup, drop, depart_at=t)     # RouteResult with eta_s, point_delay_s, turn_s
```

## 2. Point delays: signals, toll booths, level crossings

Where time is lost at a *single spot*, the router adds a fixed wait at that spot instead of making the road look slow.

| OSM | Feature | Direction |
|---|---|---|
| `highway=traffic_signals` | Signal | Only for the approach it faces if `traffic_signals:direction` / `direction` is `forward` / `backward`; otherwise both |
| `barrier=toll_booth` | Toll plaza | Both. (`highway=toll_gantry`, open-road tolling, adds no delay) |
| `railway=level_crossing` | Railway crossing | Both. Common in Indian cities, with long closures |

The wait is attached to the segment that **ends** at the node (`EdgeMeta.end_delay_s`), because you wait before crossing it.
- **Not counted at the destination:** a trip that ends at the node doesn't cross it.
- **Not learned as a slow road:** before telemetry is used, the expected wait is subtracted from the observed traversal time (`cost.moving_speed_kmh`). So a segment that always waits 30 s at its signal does **not** get a speed penalty. The same observations on a segment *without* a mapped signal do. Both cases are tested.

⚠ The waits are **assumptions**. Indian signal cycles run 90–180 s, and a random arrival waits roughly half the red phase. Next step: learn the wait per node and time bucket from telemetry, the same way the speed model learns traffic.

## 3. Speed breakers

A speed breaker (`traffic_calming=bump|hump|table|…` on a node, or on a whole way) keeps drivers slightly below the road's expected speed: ×0.9 on the segment that approaches it, or on every segment of a calmed way. It is part of the expected speed, so telemetry doesn't flag the road for it. No priority change.

## 4. Turns ([routing/turns.py](../routing/turns.py))

- **Classification from geometry:** heading change < 25° is straight, ≥ 150° (or going back along the same road) is a U-turn, otherwise left or right.
- **India drives on the left:** a **right turn crosses oncoming traffic** (far-side, expensive) and a **left turn doesn't** (near-side, cheap; often a free left). With equal route lengths, the router picks the left-turn route.
- **Turn restrictions** from OSM `type=restriction` relations: `no_*` bans that transition, and `only_*` allows only that exit. Per vehicle through `restriction:motorcar` / `restriction:motorcycle` and `except=…`. Relations with a way as the "via" member aren't supported yet and are counted.
- **Search:** the local A\* is **edge-based**: its state is the segment you arrived on, so the cost of a turn can depend on where you came from.

## 5. GraphHopper

| Feature | Stock GraphHopper 11 | Needs the import plugin ([issue 002](issues/002-graphhopper-extensions.md)) |
|---|---|---|
| Left / right turn costs | `turn_penalty` with `change_angle` in `<vehicle>.json` | |
| U-turn cost, OSM turn restrictions | `turn_costs: {vehicle_types, u_turn_costs}` in [config.yml](../deploy/graphhopper/config.yml) | |
| Per-vehicle profiles | `car`, `bike`, `auto_rickshaw` profiles | Real motorcycle / auto access (stock profiles all use `car_access`) |
| Bike / auto legal speed limits | | Category limits (stock `max_speed` is for cars) |
| Speed breakers | | `traffic_calming` encoded value |
| Point delays | | `signal_ahead` / `toll_booth_ahead` / `level_crossing_ahead` + `turn_penalty` (`extensions=True`) |

The local engine implements all of it and is the reference; the plugin brings GraphHopper to parity.

⚠ **Two things to verify on the deployed GraphHopper:**
1. **The sign of `change_angle`.** The code assumes positive = right turn (`GH_RIGHT_TURN_IS_POSITIVE`). If it's the other way round, left and right costs are swapped.
2. **Point delays through `turn_penalty`.** This only works where GraphHopper has an edge boundary at that node. See issue 002.

## 6. Assumptions to replace with data

All of these live in [vehicles.py](../routing/vehicles.py) with `ASSUMPTION` comments:
- turn costs per vehicle
- point delays
- the speed-breaker factor
- bike and auto road priorities
- auto rickshaws being exempt from tolls

Learning turn costs and signal waits from telemetry, per junction and time bucket, is the natural next step. The speed model's shrinkage and evidence tiers carry over directly.
