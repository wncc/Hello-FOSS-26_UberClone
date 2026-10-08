# Issue 004: Show how far the pickup is on the driver's ride request

**Difficulty:** 🟢 good first issue · **Area:** backend + driver app · **Skills:** Python, TypeScript/React Native

## Why
When a ride request pops up, the driver sees the fare, the pickup and drop, and the trip length, but not **how far away the pickup is**. That's the main thing a driver looks at before accepting.

## What to do
- Add `pickup_distance_m` and `pickup_eta_s` to the `ride:ping` event. The dispatcher knows the driver's position when it creates the ping.
- On the driver's ride request card, show them like "📍 1.2 km away · 4 min".

## Where to look
- `backend/app/services/dispatch.py`: where the `"ride:ping"` event is added (search for `ride:ping`). The driver's profile, with its `lat`/`lng`, is available there.
- `backend/app/services/routes.py`: `RouteService.pickup_eta` already estimates driver → pickup times.
- `mobile/src/lib/types.ts`: the `Offer` type.
- `mobile/src/app/driver/index.tsx`: the `state.mode === 'offered'` card.

## Done when
- [ ] The ping event contains both fields (extend `test_full_ride_lifecycle` in `backend/tests/test_api.py`).
- [ ] The card shows the distance and time, formatted with `formatDistance` / `formatDuration` from `mobile/src/lib/format.ts`.
- [ ] `python test_all.py` passes. The e2e screenshot of the ping step shows the new line.
