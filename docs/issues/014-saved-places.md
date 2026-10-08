# Issue 014: Saved places (Home, Work, …)

**Difficulty:** 🟡 medium · **Area:** backend + rider app · **Skills:** Python, TypeScript

## Why
Most rides start or end at the same few places. One tap on "Home" is much faster than dragging a pin every time.

## What to do
- Backend: `GET/POST/DELETE /me/places`: a name ("Home", "Work", or custom), lat/lng and an address. At most 10 per rider.
- Rider app:
  - Show saved places as quick chips on the pickup and drop steps; tapping one moves the pin there.
  - Add a "Save this place" option after confirming a pickup or drop.

## Where to look
- `backend/app/models.py` (new table), `backend/app/api/users.py` (the `/me` router).
- `mobile/src/app/rider/index.tsx`.

## Done when
- [ ] A rider can save, use and delete places, and they survive logging out and back in.
- [ ] One rider can never see another rider's places (test it).
