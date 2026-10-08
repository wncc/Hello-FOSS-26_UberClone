# Issue 006: Show how the fare is calculated

**Difficulty:** 🟢 good first issue · **Area:** backend + rider app · **Skills:** Python, TypeScript

## Why
Riders see only a total ("₹85"). Showing base fare + distance + time + booking fee builds trust, and helps when someone compares bike vs auto vs cab.

## What to do
- Make the fare calculation return its parts (base, per-km part, per-minute part, booking fee, minimum-fare top-up), not just the total.
- Include the breakdown in each `/rides/estimate` option.
- Rider app: tapping a vehicle option shows the breakdown (e.g. a small expandable section).

## Where to look
- `backend/app/services/pricing.py`: `fare_paise` and `FareCard`. Keep `fare_paise` working; add a function that returns the parts.
- `backend/app/schemas.py`: `EstimateOption`.
- `mobile/src/app/rider/index.tsx`: the option rows in the `choose` step. `formatFare` is in `mobile/src/lib/format.ts`.

## Done when
- [ ] The parts always add up to the total, including rounding up to the next rupee and the minimum fare (unit test).
- [ ] The rider can see the breakdown for each vehicle.
- [ ] `python test_all.py --quick` passes.
