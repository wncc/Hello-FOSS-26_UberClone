# Issue 017: Cancellation fee rules

**Difficulty:** 🟡 medium · **Area:** backend + apps · **Skills:** Python, product thinking

## Why
Today cancelling is always free. A driver who has driven 3 km to the pickup and waited 5 minutes gets nothing if the rider cancels.

## What to do
Propose and implement fair rules, for example:
- Free if the rider cancels within 2 minutes of the driver being assigned.
- A fee (₹25 auto, ₹50 cab, ₹15 bike) if the rider cancels later, or more than 5 minutes after the driver arrived.
- No fee if the driver was very late (e.g. more than 10 minutes past the ETA shown at assignment).

Store the fee on the ride, show it **before** the rider confirms cancelling ("A ₹25 fee applies"), and show it to the driver.

## Where to look
- `backend/app/services/rides.py`: `cancel_ride`.
- `mobile/src/app/rider/ride/[id].tsx`: the cancel confirmation (`confirmAction`).

## Done when
- [ ] The rules live in configuration and are covered by tests for each case.
- [ ] The rider sees the fee before confirming.
