# Issue 019: Share my trip, and an SOS button

**Difficulty:** 🟡 medium · **Area:** backend + rider app · **Skills:** Python, TypeScript, web

## Why
Safety features are expected in Indian ride-hailing apps. Riders, especially at night, want family to follow the trip live and a quick way to get help.

## What to do
1. **Share trip:**
   - A "Share trip" button creates a link (with a random, unguessable token) to a simple read-only web page. The page shows the driver's name, vehicle number, live position and destination.
   - It works without logging in and expires when the trip ends.
   - Use the phone's share sheet (`Share` from React Native).
2. **SOS:** a button during the trip that:
   - shows the emergency number 112 to call (opened with a `tel:` link);
   - records an SOS event on the ride with the current position, so operations staff can follow up.

## Where to look
- `backend/app/api/rides.py` (new endpoints), `backend/app/main.py` (the public share page could be a small HTML page served by FastAPI, refreshing every 5 seconds).
- `mobile/src/app/rider/ride/[id].tsx`.

## Done when
- [ ] The share link shows live progress in any browser and stops working after the trip.
- [ ] Tokens can't be guessed, and the page never shows the rider's phone number or PIN.
- [ ] Tests for token expiry and access.
