# Issue 027: Run more than one backend instance (Redis for live events)

**Difficulty:** 🔴 hard · **Area:** backend, scaling · **Skills:** Python asyncio, Redis, distributed systems

## Why
Today everything assumes **one** backend process:
- live events go only to apps connected to that process;
- the dispatch loop runs inside it.
Two instances would mean riders missing events and rides matched twice.

## What to do
- **Live events:** publish them through Redis pub/sub. Each instance delivers to the apps connected to it.
- **Dispatch:** make sure only one instance runs the matching cycle at a time (a Redis lock, or a separate dispatch worker process).
- **Ride assignment:** use database row locks (with issue 020) so two cycles can never assign the same ride.
- Keep a no-Redis mode for development and tests.

## Where to look
- `backend/app/services/realtime.py`: `Hub` (in-memory, one process).
- `backend/app/services/dispatch.py`: `Dispatcher` (the `asyncio.Lock` only works within one process).
- `docs/BACKEND.md`: known gaps.

## Done when
- [ ] With two backend instances behind one address, a rider connected to instance A gets events produced by instance B.
- [ ] A test or script shows a ride is never assigned twice when both instances run dispatch.
