# Ride Matching Engine

## What this does
Every 3 seconds, this service:
1. Fetches current `drivers` and `riders` from your backend (`GET {EXTERNAL_API}/state`).
2. **Resolves conflicts** — if multiple drivers accepted the same rider (broadcast pings), keeps the nearest (Haversine distance), frees the rest.
3. **Assigns new pings** — for `free` drivers and `ping_pending` riders, uses Redis `GEOADD`/`GEOSEARCH` to find free drivers within 4km of each pending rider, holds back 20% of free drivers in reserve, and pings up to 3 random eligible drivers per rider (broadcast).
4. **Writes the result back** (`POST {EXTERNAL_API}/update`) with updated statuses.

It never decides accept/reject itself — that must happen on your backend (driver taps Accept/Reject), and gets picked up on the next cycle.

## Statuses
- **Driver**: `free` → `pinged` (one rider only) → `accepted` | back to `free`
- **Rider**: `ping_pending` → `driver_pinged` (`driverIds`: candidates) → `accepted` (`driverId`: winner)

## Contract your backend must implement

**`GET /state`** → returns:
```json
{
  "drivers": [{ "id": "D1", "lat": 12.97, "lng": 77.59, "status": "free", "riderId": null }],
  "riders":  [{ "id": "R1", "lat": 12.98, "lng": 77.60, "status": "ping_pending", "driverId": null, "driverIds": [] }]
}
```
`lat`/`lng` must be numbers.

**`POST /update`** → receives the same shape back; store it as your new source of truth.

## Integrating with the rest of your Uber-style backend
This engine doesn't talk to phones directly — your backend (WebSocket server) does. The glue code lives in your backend's `/update` handler:

1. **Before** overwriting your stored state, diff old vs. new per driver/rider id:
   - status flipped to `pinged` → emit `ride:ping` to that driver's socket (with rider's location)
   - status flipped to `accepted` (rider side) → emit `ride:matched` to that rider's socket, `ride:confirmed` to the winning driver
   - status flipped from `pinged`/`accepted` back to `free` → emit `ride:taken`/`ride:rejected` to that driver
2. When a driver's phone sends GPS (every 2-4s) or taps Accept/Reject, update your stored driver/rider records accordingly — this engine will pick up the change on its next `GET /state`.
3. Keep this engine and your WebSocket backend as separate processes/services; they only communicate over the `/state` and `/update` HTTP contract above.

## Config (top of file)
| Var | Meaning |
|---|---|
| `EXTERNAL_API` | Base URL of your backend |
| `REDIS_URL` | Redis connection string (**use env var, never hardcode**) |
| `RADIUS_KM` | Ping radius |
| `RESERVE_RATIO` | Fraction of free drivers held back per cycle |
| `MAX_DRIVERS_PER_RIDER` | Broadcast fan-out cap |
| `TICK_MS` | Cycle interval |