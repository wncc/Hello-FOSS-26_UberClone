# Issue 005: Let riders add a pickup note ("Gate 2, near the ATM")

**Difficulty:** 🟢 good first issue · **Area:** backend + both apps · **Skills:** Python, TypeScript

## Why
In Indian cities a map pin is often not enough: riders say "society gate 2", "opposite the temple", "blue building". Drivers waste time calling.

## What to do
- Add an optional `pickup_note` (max 120 characters) when booking.
- Store it on the ride and show it to the driver: on the ride request card and on the trip screen until pickup.
- Rider app: add an optional text field on the fare screen, above the **Book** button.

## Where to look
- `backend/app/models.py`: the `Ride` table (add a column).
- `backend/app/schemas.py`: `RideCreateIn`, `RideOut`.
- `backend/app/services/rides.py`: `create_ride`, and `ride_summary` (the data sent with ride events).
- `mobile/src/app/rider/index.tsx` (the `choose` step), `mobile/src/app/driver/index.tsx`, `mobile/src/app/driver/trip/[id].tsx`.

**Note:** there are no database migrations yet (see issue 020). After adding a column, delete your local `uberclone.db`.

## Done when
- [ ] The note is optional and limited to 120 characters (422 if longer).
- [ ] The driver sees it on the request card and the trip screen; the rider sees what they typed.
- [ ] Backend test plus a step in `e2e/run_e2e.py` that types a note and checks the driver screen shows it.
