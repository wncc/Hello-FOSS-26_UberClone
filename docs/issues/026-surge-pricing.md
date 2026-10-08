# Issue 026: Surge pricing when demand is higher than supply

**Difficulty:** 🔴 hard · **Area:** backend + rider app · **Skills:** Python, data, product design

## Why
At rush hour or in the rain, riders far outnumber drivers. Higher fares bring more drivers online and keep waiting times reasonable. It needs to be fair and clearly explained.

## What to do
- Split the city into zones (e.g. H3 cells at resolution 7, or a simple lat/lng grid).
- Every minute, count waiting riders and free drivers per zone and vehicle type. Turn that into a multiplier, e.g. 1.0–2.0×, smoothed over time so it doesn't jump around.
- Apply the multiplier to estimates and store it on the ride. The multiplier at booking time is what the rider pays.
- Rider app: show "Fares are higher right now (1.4×)" before booking.
- Put the caps and the formula in configuration, and add a switch to turn surge off completely.

## Where to look
- `backend/app/services/pricing.py`, `backend/app/api/rides.py` (`estimate`, `book`).
- `backend/app/services/dispatch.py`: already loads searching rides and online drivers every cycle.

## Done when
- [ ] Tests: zones with more riders than drivers get a multiplier above 1; balanced zones stay at 1.0; it never exceeds the cap.
- [ ] The rider sees the surge before booking, and the fare charged matches what was shown.
