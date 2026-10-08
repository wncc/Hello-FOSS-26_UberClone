# Testing

## One command for everything

```powershell
# from the repo folder (same on Windows, macOS and Linux)
python test_all.py            # all checks + the browser ride test (~3-5 min), then opens the report
python test_all.py --quick    # skip the browser ride (~20 s)
```

| Check | What it covers |
|---|---|
| Python tests (pytest) | Routing (road hierarchy, telemetry, legal limits, access, tolls, zones, turns, delays, snapping), matching engine, backend API (a full ride, auth, cancellations, timeouts, WebSocket, admin, road-following routes) |
| App typecheck + lint | Every screen and library in `mobile/` |
| App unit tests (jest) | Fare/distance formatting, ride state machines, socket reconnects, API client, the map page against the real Leaflet library |
| **End-to-end ride** (`e2e/run_e2e.py`) | A rider phone and a driver phone (browser, 390×844, GPS set in Dadar) play a complete ride through the real UI against the real backend with Mumbai roads. Every step checks what's on screen, and screenshots both phones |

The end-to-end report is at `e2e/report/index.html`. Each step shows PASS/FAIL, what was checked, and the rider and driver screenshots side by side.

Checks include:
- the map loaded with tiles
- the road route is drawn (point count: a straight line would be 2) and fully in view
- the driver's path to the pickup is shown
- fares are listed for all vehicles
- a wrong PIN is rejected
- the ride appears in history and earnings

To watch it run in real browser windows: `python e2e/run_e2e.py --headed --slow-mo 400`.

The browser test runs the same app code as the phone. The only browser-specific parts are the map container (an iframe instead of a native WebView, both showing the same Leaflet page), token storage, and confirmation dialogs. Phone-only features aren't covered: background GPS, native keyboard behaviour, and address names (the phone's geocoder; the browser shows coordinates).

## Watching a ride on your phone (demo mode)

```powershell
# from the repo folder (same on Windows, macOS and Linux)
python demo.py                          # backend + automatic cab, auto and bike drivers near Dadar
python demo.py --near 19.0596,72.8295   # drivers near your own location
```

Then, in a second window: `cd mobile ; npm run start:rider`, scan the QR code with Expo Go, and book near the drivers. The driver for the vehicle you booked:
1. accepts
2. drives the roads to you (watch the car move)
3. starts the trip by itself, without you reading out the PIN
4. drives to the drop and completes

You rate, and the ride shows in your history. Stop the demo with Ctrl+C.

`demo.py` starts its own backend on port 8000. If another backend is already running, it says so and stops; close that one first.
