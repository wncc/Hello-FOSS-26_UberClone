# Map data: speed limits, access, tolls, restricted zones

This doc covers what the router knows about **legal** constraints and where each piece comes from. Everything is extracted **per vehicle** (car, bike, auto rickshaw); signals, toll booths, level crossings, speed breakers and turn restrictions are covered in [VEHICLES_AND_TURNS.md](VEHICLES_AND_TURNS.md). For road preference, see [ROUTING.md](ROUTING.md). For telemetry learning, see [ROAD_LEARNING.md](ROAD_LEARNING.md).

## Getting the data

Everything comes from **OpenStreetMap**, plus polygons your ops team defines.

```bash
# 1. Download the regional extract (India is split into zones), e.g. southern zone:
#    https://download.geofabrik.de/asia/india.html
# 2. Clip to the operating city (bbox = min_lon,min_lat,max_lon,max_lat):
osmium extract -b 77.45,12.83,77.78,13.14 southern-zone-latest.osm.pbf -o city.osm.pbf
# 3. Build road metadata + zones (pip install osmium):
python -m routing.osm_import city.osm.pbf --out data/roads.pkl --bbox <min_lat,min_lng,max_lat,max_lng> --city-cap 50
#    (--bbox clips a regional extract directly; .pkl loads fast, .json is human-readable)
```

`roads.json` contains, per vehicle, every drivable directed segment (`EdgeMeta`) and the turn restrictions, plus every restricted zone, plus coverage counts. The counts show, for example, how many segments have a posted limit versus a legal default, and how many time-based closures couldn't be parsed. Load it with `osm_import.load()` and build `MultiVehicleRouter.local(extract, buckets=...)`, or pass each vehicle's edges to a `RoutingService`.

**Run GraphHopper on the same `city.osm.pbf`**, so segment IDs (`<way>:<from node>:<to node>`) match between routing and telemetry.

## What is extracted

| Data | OSM source | Stored as | Routing effect |
|---|---|---|---|
| **Speed limit** | `maxspeed`, `maxspeed:forward` / `:backward`, `maxspeed:motorcar` / `:motorcycle` (numbers, `mph`, `walk`, zone codes like `IN:urban`, `IN:zone30`). Bikes and autos never exceed their category maximum | `max_speed_kmh`, `max_speed_source = sign` | Speed never exceeds the limit (`limit_to max_speed`) |
| **Legal default limit** (no sign mapped) | Road type + whether it's divided | `max_speed_source = legal_default` | Same |
| **Private / no-entry / delivery-only roads** | `access`, `vehicle`, `motor_vehicle`, `motorcar` (the most specific tag wins) | `road_access` = PRIVATE / NO / DELIVERY | **Blocked** (priority 0) |
| **Destination-only roads** (residents, customers) | `…=destination`, `…=customers` | `road_access = DESTINATION` | ×0.1: usable for a pickup or drop-off on that road, not as a shortcut |
| **Time-based closures** | `motorcar:conditional`, `motor_vehicle:conditional`, `vehicle:conditional`, `access:conditional`, e.g. `no @ (Mo-Fr 08:00-10:00)` | `no_access_buckets` | Blocked only when the departure time falls in those hours |
| **Toll roads** | `toll`, `toll:motorcar`, `toll:hgv` | `toll` = ALL / HGV / NO / MISSING | Listed in `RouteResult.toll_segments`. ×0.1 when the rider picks `RouteOptions(avoid_tolls=True)` |
| **Military areas** | `landuse=military`, `military=*` | `RestrictedZone(kind=NO_ENTRY, source="osm")` | Every road inside is blocked |
| **Ops zones** (airport forecourt, VIP or event areas, gated townships) | GeoJSON from ops → `RestrictedZone(kind=NO_ENTRY / AVOID / DESTINATION_ONLY, active_buckets=…)` | Same | Blocked / ×0.1 / ×0.1, optionally only at certain hours |
| **One-way** | `oneway`, motorways, roundabouts | Only the permitted direction is created | Wrong direction doesn't exist |

In GraphHopper these become the encoded values `max_speed`, `road_access`, `toll` and `in_zone_<id>` areas ([config.yml](../deploy/graphhopper/config.yml), [car.json](../deploy/graphhopper/car.json)). GraphHopper also blocks roads it considers inaccessible (`car_access`) and barrier nodes (gates, bollards) on its own.

## Speed limits

**Where a sign is mapped, it is used as-is** (for bikes and autos, capped at their category maximum). Where it isn't, the national maximum from **MoRTH notification S.O. 1522(E), 6 April 2018** applies. For cars (`INDIA_M1`, category M1, ≤ 8 passenger seats) that's below; bikes use 80/80/60 and autos 50, with autos barred from expressways ([VEHICLES_AND_TURNS.md](VEHICLES_AND_TURNS.md)):

| Road | Limit |
|---|---|
| Expressway (`highway=motorway`) | 120 km/h |
| Four-lane-or-more divided highway (divided `trunk` / `primary`) | 100 km/h |
| Roads within municipal limits, and all other roads | 70 km/h |

⚠ **Check these defaults:**
- Secondary sources disagree on the urban figure (some quote 60 km/h). Verify against the gazette text.
- **These are national maximums. States and cities notify lower limits** (Delhi, Bengaluru and others often set 40–60 km/h). Pass the city's figure as `--city-cap`; it applies to every non-expressway default, never to posted signs.
- GraphHopper computes its own defaults from the [osm-legal-default-speeds](https://github.com/westnordost/osm-legal-default-speeds) rules (`max_speed_calculator.enabled`). Its numbers can differ from ours where no sign is mapped.

**How limits interact with the uniform speed:** the expected speed of every road is `min(30 km/h, legal limit)`. Today, limits only bite where they're below 30 km/h: living streets, school zones, posted 20s. Every higher limit is already recorded, so issue 001 (per-road speeds) can use it directly. `RoutingService` rejects edges whose `speed_kmh` isn't `expected_speed_kmh(max_speed_kmh)`, because telemetry measures slowness against that value.

## Known gaps

- **OSM coverage is uneven in Indian cities.** Posted limits, tolls and access tags are often missing. The `roads.json` stats show how much is covered for your city. Filling gaps (by drivers, ops or map edits) directly improves routing.
- **Toll amounts are not in OSM.** Fares need a separate toll-plaza table; NHAI publishes fee plazas and rates.
- **Complex time conditions are skipped rather than guessed.** Dates, holidays, month ranges and weight or wet-weather conditions are counted as `conditional.unparsed`. Weekdays share one time profile, so "Mo,We 08:00-10:00" is treated as every weekday: stricter, never looser.
- **Restrictions and pickups.** A NO_ENTRY zone or a private road also means no route *into* it. Pickups inside gated areas should snap to the gate (GraphHopper snapping only uses accessible roads).
- **Unknown speed limits in GraphHopper.** `limit_to max_speed` assumes GraphHopper treats an unknown limit as "no limit". With the legal-default calculator on, nearly every road has a value, but confirm this on the deployed version.
