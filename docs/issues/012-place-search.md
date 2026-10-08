# Issue 012: Search for pickup and drop places (not just dragging a pin)

**Difficulty:** 🟡 medium · **Area:** backend + rider app · **Skills:** Python, TypeScript, APIs
**Reported in:** the project README ("no search function only pin drag and drop")

## Why
Today the only way to choose a pickup or drop is to drag the map under a pin. Riders expect to type "Phoenix Mall" or "Dadar station" and pick from suggestions.

## What to do
1. **Backend: `GET /places/search?q=…&near=lat,lng`**, returning up to 8 results, each with a name, a short address, and lat/lng.
   - Put the provider behind a small interface so it can be swapped. Good free options for development are [Photon](https://photon.komoot.io) and [Nominatim](https://nominatim.org). Read their usage policies: send a proper `User-Agent`, at most 1 request per second, no bulk use. India-focused paid options (Ola Maps, Mappls, Google Places) can be added later behind the same interface.
   - Bias results to the area near the rider, and cache repeated queries.
2. **Rider app:** a search box at the top of the pickup and drop steps.
   - Debounce typing (about 300 ms) and show suggestions in a list.
   - Choosing a result moves the map there (`recenterTo`) and fills in the address. The pin stays draggable to fine-tune.
3. Add a "Recent places" list under the search box. It can share storage with saved places (issue 014).

## Where to look
- `mobile/src/app/rider/index.tsx`: steps `pickup` / `drop`, `setRecenterTo`, `label`.
- `mobile/src/lib/api.ts`: add `searchPlaces`.
- `backend/app/api/`: add a `places.py` router and include it in `backend/app/main.py`.

## Done when
- [ ] Typing "Dadar station" shows matching suggestions near Mumbai, and picking one sets the pickup there.
- [ ] Without internet, or when the provider fails, search shows a friendly message and pin dragging still works.
- [ ] Backend test with a fake provider (no real network calls in tests), plus an e2e step that books using search.
