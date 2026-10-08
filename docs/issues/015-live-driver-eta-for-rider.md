# Issue 015: "Arriving in 4 min" for the rider

**Difficulty:** 🟡 medium · **Area:** backend + rider app · **Skills:** Python, TypeScript

## Why
After a driver is assigned, the rider sees the car move on the map, but not **how long until it arrives**. It's the most-watched number in any ride-hailing app.

## What to do
- Backend: include the estimated time for the driver to reach the pickup:
  - in `GET /rides/{id}/route`, while the driver is on the way (the `approach` route already exists);
  - and, about every 15 seconds, along with `driver:location` events.
- Rider app: show "Arriving in N min" on the ride screen, updating live, and switch to "Driver has arrived" when it happens.
- Avoid recalculating a road route on every GPS update; once every 15–30 seconds is enough.

## Where to look
- `backend/app/api/rides.py`: `ride_route` (computes `approach` with `ctx.routes.estimate`).
- `backend/app/services/locations.py`: sends `driver:location` to the rider.
- `mobile/src/app/rider/ride/[id].tsx`, `mobile/src/lib/useRideRoute.ts`.

## Done when
- [ ] The countdown appears once a driver is assigned and goes down as the driver approaches (the simulator from `demo.py` is a good way to watch it).
- [ ] Tests cover the new field.
