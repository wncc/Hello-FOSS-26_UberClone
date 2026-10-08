# Issue 011: More end-to-end scenarios: cancellations and "no drivers"

**Difficulty:** 🟢 good first issue · **Area:** testing · **Skills:** Python, Playwright

## Why
The browser test (`e2e/run_e2e.py`) covers the happy path: a ride from booking to rating. Things that go wrong in real life aren't tested through the UI yet.

## What to do
Add scenarios. Each should start from a fresh login so it doesn't depend on the others:
1. **The rider cancels while searching.** The rider sees "Ride cancelled" and can book again.
2. **The rider cancels after the driver is assigned.** The driver's trip screen tells them, and they're back on the home screen.
3. **The driver cancels after accepting.** The rider sees the search start again.
4. **No drivers nearby.** The search ends with "No drivers available right now". You'll need a shorter search timeout for the test backend (`SEARCH_TIMEOUT_SECONDS`, which you'll have to add to `Settings`).

## Where to look
- `e2e/run_e2e.py`: `scenario()` and the `see` / `button` helpers. Cancelling shows a browser `confirm()` dialog; accept it with `page.on("dialog", lambda d: d.accept())`.
- `backend/app/config.py`: `search_timeout_seconds` is hard-coded to 180.

## Done when
- [ ] Each scenario has PASS steps with screenshots in `e2e/report/index.html`.
- [ ] `python test_all.py` passes.
