# Issue 016: Final fare from the actual trip (distance driven + waiting time)

**Difficulty:** 🟡 medium · **Area:** backend · **Skills:** Python, geometry

## Why
The final fare is simply the estimate made at booking. If the driver has to take a detour, or the rider makes the driver wait at pickup, the fare doesn't change.

## What to do
- When a trip completes, calculate the distance actually driven from the driver's GPS breadcrumbs (`LocationPing` rows with this `ride_id`, between `started_at` and `completed_at`).
- Add a waiting charge after a free waiting period (e.g. 3 minutes after `arrived_at`, then ₹1 per minute). Put the numbers on the fare card.
- Protect riders from GPS glitches: ignore impossible jumps (over 150 km/h between points), and cap the final fare at, say, 1.5× the estimate unless the drop was changed.
- Store the breakdown and show it on the completion screen for both rider and driver.

## Where to look
- `backend/app/services/rides.py`: `complete_ride` (`fare_final_paise = fare_estimate_paise`).
- `backend/app/models.py`: `LocationPing`, `Ride.arrived_at` / `started_at`.
- `backend/app/services/pricing.py`.

## Done when
- [ ] Unit tests with synthetic GPS tracks: a normal trip, a detour, a GPS glitch, and a long wait at pickup.
- [ ] The completion screen shows the final fare and why it differs from the estimate.
