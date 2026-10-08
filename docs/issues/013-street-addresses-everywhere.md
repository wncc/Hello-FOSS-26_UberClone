# Issue 013: Show street addresses instead of coordinates

**Difficulty:** 🟡 medium · **Area:** backend + apps · **Skills:** Python, TypeScript

## Why
Addresses come from the phone's own geocoder, and only when it works. In the browser, on some phones, and in ride history you often see "19.01780, 72.84780" instead of "Dadar West, Mumbai". Drivers see raw coordinates too.

## What to do
- Backend: when a ride is booked without an address, look one up from the coordinates (reverse geocoding). Use the same swappable provider and usage-policy rules as issue 012.
- Save the address on the ride, so history and the driver's screens always have it.
- Apps: everywhere coordinates are shown (pickup/drop panels, ride request card, trip screen, history), show the address, falling back to coordinates only if there is none.

## Where to look
- `mobile/src/lib/location.ts`: `addressLabel` (phone geocoder).
- `mobile/src/lib/format.ts`: `shortAddress`.
- `backend/app/services/rides.py`: `create_ride` (sets `pickup_address` / `drop_address`).

## Done when
- [ ] A ride booked from the browser shows a street address in history and on the driver's screens.
- [ ] Lookups are cached and never block booking for more than about 2 seconds (fall back to coordinates).
- [ ] Tests use a fake provider.
