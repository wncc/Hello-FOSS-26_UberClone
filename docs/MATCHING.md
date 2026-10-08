# Ride matching

[matching/](../matching/) is the Python port of [ride-matching-engine-uber-main](../ride-matching-engine-uber-main/) (Node), integrated with the routing engine. It keeps the same backend contract and statuses, so a backend written for the Node version works unchanged. It needs no Redis.

```bash
EXTERNAL_API=http://backend:4000 python -m matching.server                     # straight-line pickup distance
python -m matching.server --api http://backend:4000 --roads roads.json         # road-network pickup ETAs
python -m matching.server --selection nearest --once                           # one cycle, print stats
```

## Algorithm (every `TICK_MS`, default 3 s; cycles never overlap)

1. `GET /state` → drivers and riders.
2. **Resolve acceptances.** If several drivers accepted the same rider, the one with the **shortest pickup** wins (road ETA with `--roads`, straight-line otherwise). An already confirmed match is kept. The other acceptors are freed.
3. **Clean up:**
   - drivers still pinged for a rider who is now matched or cancelled are freed
   - pings unanswered after `ping_timeout_s` (20 s) are freed
   - riders whose pinged drivers all rejected or timed out go back to `ping_pending`
   - riders whose matched driver cancelled (backend set the driver `free`) go back to `ping_pending`
4. **Ping.** Hold back 20% of free drivers. For each pending rider, take free drivers within `radius_km` (4 km) **of the same vehicle type**. With `--roads`, keep the `eta_candidates` (10) nearest and drop anyone whose pickup ETA is over `max_pickup_eta_s` (15 min) or who can't reach the rider by road. Ping up to 3: chosen at random (`random`, the original fair spread) or the lowest ETAs (`nearest`).
5. `POST /update` with the same records. Fields the engine doesn't know about pass through untouched.

The engine never accepts or rejects for a driver; the backend does that when the driver taps a button.

## Contract changes vs. the Node version

| Field | On | Meaning |
|---|---|---|
| `vehicle` | driver, rider | `car` (default if missing), `auto_rickshaw` or `bike`. Rider = requested type. **New**: the backend should send it |
| `pingedAt` | driver | Epoch ms when the engine pinged this driver; used for the timeout. Written by the engine, and the backend must store it back like any other field |

Everything else (statuses, `riderId`, `driverId`, `driverIds`, `lat`/`lng` as numbers) is unchanged. A record with a missing or non-numeric `lat`/`lng` or an unknown `vehicle` is skipped and counted in `invalid_records`; it no longer stops the whole cycle.

## Errors found in the Node version

All fixed in the port, with a regression test in [tests/test_matching.py](../tests/test_matching.py) for each:

| # | Problem | Effect |
|---|---|---|
| 1 | No `package.json`, `redis` not installed | Service doesn't start (`ERR_MODULE_NOT_FOUND`) |
| 2 | `createClient({ url: "process.env.REDIS_URL" })` is a string literal | Would connect to an invalid URL even with Redis installed |
| 3 | Pinged drivers not released when their rider is matched to someone else | Those drivers stay `pinged` forever and stop receiving rides |
| 4 | No ping timeout | A driver who ignores a ping is stuck, and so is the rider |
| 5 | A rider whose drivers all rejected stays `driver_pinged` | Never re-pinged |
| 6 | A confirmed match is re-evaluated every cycle | A later, nearer acceptor can steal a confirmed ride |
| 7 | A driver accepted for a cancelled rider is never freed | Driver stuck in `accepted` |
| 8 | No vehicle type | A car can be pinged for an auto-rickshaw request |
| 9 | Pickup distance is straight-line | A driver "1 km away" across a river is preferred over one 2 minutes away by road |
| 10 | One record with bad coordinates makes Redis `GEOADD` throw | No one is matched that cycle |

Redis was used only as a per-cycle radius index: it was deleted and rebuilt from `/state` every cycle. An in-memory grid index ([matching/geo.py](../matching/geo.py)) does the same job without a separate service.

## Notes

- **Scale.** Road ETAs cost one route per candidate. The local A\* is fine for tests and small areas. For a city, use GraphHopper backends in `MultiVehicleRouter`, or a one-to-many / matrix call.
- **Fairness.** `random` (the default, as in the original) spreads pings across nearby drivers. `nearest` minimizes pickup time. Both only consider drivers inside the radius and, with `--roads`, under the ETA cap.
- **Multiple instances.** Run one instance per city or region. Two engines working on the same `/state` would ping the same drivers twice; the original has the same limitation.
