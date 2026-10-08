# Issue 009: Weekly earnings summary for drivers

**Difficulty:** 🟢 good first issue · **Area:** backend + driver app · **Skills:** Python, TypeScript

## Why
Drivers see only **today's** cash earnings. Most drivers plan by the week: how many trips, how much, and which days were good.

## What to do
- Add `GET /drivers/me/earnings?days=7`, returning total earnings, trip count and a per-day list, all for completed rides.
- Driver app: on the Earnings screen, show the week total and a simple per-day bar list under today's figure.
- Count days in India time (IST), not UTC.

## Where to look
- `backend/app/api/drivers.py`: add the endpoint. `Ride.fare_final_paise` and `Ride.completed_at` hold the data.
- `routing/time_buckets.py` has an `IST` timezone you can reuse.
- `mobile/src/components/RideHistory.tsx`: today's earnings are calculated here from ride history.

## Done when
- [ ] A ride completed at 23:30 IST counts for that day, not the next (test it).
- [ ] The earnings screen shows the week.
- [ ] Backend tests pass.
