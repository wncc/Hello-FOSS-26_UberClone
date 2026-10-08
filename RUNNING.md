# How to run the project

> **Want to contribute?** Open issues, from 🟢 good first issues to 🔴 hard ones, are listed in the [README](README.md#open-issues).

All commands are for **Windows PowerShell**, from the repo folder (`D:\UberClone`) unless a step says `cd mobile`. Stop anything that's running with **Ctrl+C** in its window.

**Pick your case:**

| I want to… | Go to |
|---|---|
| Set up a new laptop | [A. First-time setup](#a-first-time-setup) |
| Try the rider app on my phone, with no second person | [B. Phone + automatic drivers (demo)](#b-phone--automatic-drivers-demo) |
| Use both apps, on two phones | [C. Two phones](#c-two-phones-rider--driver) |
| Test the driver app with only one phone | [D. One phone as the driver](#d-one-phone-as-the-driver) |
| Use the apps without a phone (in a browser) | [E. No phone: browser](#e-no-phone-run-in-the-browser) |
| Check everything works (automatic tests) | [F. Run all tests](#f-run-all-tests) |
| Use a city other than Mumbai | [G. Another city](#g-another-city) |
| Start over with empty data | [H. Reset](#h-reset-everything) |
| Something doesn't work | [Troubleshooting](#troubleshooting) |

---

## A. First-time setup

Do this once per laptop. On this laptop it's already done.

1. **Install the tools** (if missing): Python 3.11+ (3.13 is used here), Node.js 20+ (24 is used here) and Git.
2. **Install Python packages:**
   ```powershell
   python -m pip install -r requirements-dev.txt
   python -m playwright install chromium
   ```
3. **Install app packages:**
   ```powershell
   cd mobile
   npm install
   cd ..
   ```
   If PowerShell says "running scripts is disabled", type `npm.cmd` instead of `npm` everywhere.
4. **Build the Mumbai road data.** Routes follow real roads only if `data\roads.pkl` exists; without it they're straight lines. The file isn't in git (it's 173 MB), so each laptop builds it once: a 221 MB download plus about a 5-minute import.
   ```powershell
   mkdir data
   curl.exe -L -o data\western-zone-latest.osm.pbf https://download.geofabrik.de/asia/india/western-zone-latest.osm.pbf
   python -m routing.osm_import data\western-zone-latest.osm.pbf --out data\roads.pkl --bbox 18.89,72.77,19.30,73.05
   ```
5. **Let your phone reach the laptop.** In Windows: **Settings → Network & internet → Wi-Fi → (your network) → Network profile type → Private**. Or run this once in an **Administrator** PowerShell:
   ```powershell
   New-NetFirewallRule -DisplayName "UberClone dev" -Direction Inbound -Protocol TCP -LocalPort 8000,8081,8082 -Action Allow
   ```
6. **Install Expo Go** on your phone from the Play Store or App Store, and keep it updated. The app uses Expo SDK 57.

The phone and laptop must be on the **same Wi-Fi**. College and office networks often block devices from talking to each other. If that happens, turn on your phone's hotspot and connect the laptop to it.

---

## B. Phone + automatic drivers (demo)

The easiest way to see a whole ride. Simulated drivers do everything on the driver side.

**Window 1** (backend + 3 automatic drivers: cab, auto, bike):
```powershell
python demo.py
```
Wait for `Demo running`; loading the Mumbai roads takes about 20 seconds. The drivers wait near **Dadar**. To put them near you, pass your location (in Google Maps, long-press your spot and copy the numbers):
```powershell
python demo.py --near 19.0596,72.8295
```

**Window 2** (rider app):
```powershell
cd mobile
npm run start:rider
```
Scan the QR code. On Android, scan it inside **Expo Go**; on iPhone, use the **Camera** app.

**On the phone:**
1. Enter any 10-digit mobile number and tap **Send code**. The code `123456` fills itself in; tap **Verify** and enter your name.
2. Drag the map to place your pickup, then tap **Confirm pickup**. Drag again for the drop and tap **Confirm drop**. Keep both within about 4 km of the drivers.
3. Choose **Bike / Auto / Cab**, then tap **Book**.
4. Watch: the driver is assigned, drives along the roads to you, starts the trip by itself (no need to read out the PIN), drives to the drop and completes. Then rate the driver.

`demo.py` starts its own backend. If another backend is already running, the demo says so and stops; close that one first (Ctrl+C in its window).

---

## C. Two phones (rider + driver)

You need two phones, and two different mobile numbers: each number is either a rider or a driver.

**Window 1** (backend):
```powershell
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```
Wait for `road data ready` and `Application startup complete`.

**Window 2** (rider app, port 8081):
```powershell
cd mobile
npm run start:rider
```

**Window 3** (driver app, port 8082):
```powershell
cd mobile
npm run start:driver
```

Scan each QR code with a different phone.

- **Driver phone:**
  1. Log in and set up the vehicle: type, registration number and model.
  2. Tap **Go online** and keep the app open; the screen stays on.
- **Rider phone:** book within 4 km of the driver, choosing the **same vehicle type** as the driver's.
- **The ride:**
  1. The driver sees a ping with a 20-second countdown and taps **Accept**.
  2. The driver taps **Navigate** (opens Google Maps), then **I've arrived**.
  3. The driver types the **PIN** shown on the rider's phone, then taps **Start trip**.
  4. At the drop, the driver taps **Complete trip** and collects the cash.
  5. Both rate each other.

---

## D. One phone as the driver

**Window 1** (backend), as in C:
```powershell
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

**Window 2** (driver app):
```powershell
cd mobile
npm run start:driver
```
On the phone: log in, set up the vehicle, and **Go online**.

**Window 3** (a simulated rider who books a ride; pickup and drop are `lat,lng`):
```powershell
python -m backend.tools.simulate rider --pickup 19.0178,72.8478 --drop 19.0607,72.8636 --vehicle auto_rickshaw
```
Use the same vehicle type as your driver, and a pickup within 4 km of the phone. The window prints the **PIN** to type on the phone when you arrive, and follows the ride until it's completed.

To control a simulated driver yourself (it asks you for the PIN), see `python -m backend.tools.simulate driver --help`.

---

## E. No phone: run in the browser

**Watch an automatic ride in real browser windows:**
```powershell
python e2e/run_e2e.py --headed --slow-mo 400
```
This opens two phone-sized windows, a rider and a driver, and plays a complete ride through the real apps. You don't need to start anything else: it starts its own backend and builds the apps. When it finishes, the report with screenshots is at `e2e\report\index.html`.

**Use the app yourself in a browser:**
1. Start the backend, as in C, Window 1.
2. Run `cd mobile`, then `npm run start:rider`, then press **`w`**.
3. Allow location in the browser.

The browser shows coordinates instead of street names, and confirmation dialogs are browser pop-ups. Everything else works as on the phone.

---

## F. Run all tests

```powershell
python test_all.py            # everything, ~3-5 minutes, then opens the screenshot report
python test_all.py --quick    # without the browser ride, ~30 seconds
```

The summary at the end shows PASS / FAIL for each part:

| Part | What it checks |
|---|---|
| Python tests | Routing, matching, backend API |
| App checks | Typecheck, lint, app unit tests |
| Browser ride | The full ride through the real UI |

The report (`e2e\report\index.html`) shows what was checked at each step, with rider and driver screenshots side by side. More detail is in [docs/TESTING.md](docs/TESTING.md).

You don't need to close other windows for the tests; they use their own ports (8790–8792). They do need `data\roads.pkl`, or the route checks fail.

---

## G. Another city

1. Find the city's region file on [Geofabrik India](https://download.geofabrik.de/asia/india.html). India is split into zones: Mumbai and Pune are in the western zone, Delhi in the northern zone, Bengaluru in the southern zone.
2. Find the city's bounding box as `min_lat,min_lng,max_lat,max_lng`. For example, Bengaluru is about `12.83,77.45,13.14,77.78`.
3. Build the road data:
   ```powershell
   curl.exe -L -o data\southern-zone-latest.osm.pbf https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf
   python -m routing.osm_import data\southern-zone-latest.osm.pbf --out data\roads.pkl --bbox 12.83,77.45,13.14,77.78
   ```
4. Restart the backend.
5. For a better first view, change `DEFAULT_CENTER` in `mobile/src/lib/location.ts` and the default locations in `demo.py` and `backend/tools/simulate.py` to the new city.

Only one city is loaded at a time. To run without road data (straight-line estimates), run `$env:ROADS_PATH="none"` in the same window before starting the backend.

---

## H. Reset everything

All local data lives in one file: users, rides and ratings.
1. Stop the backend.
2. Delete `uberclone.db` in the repo folder.
3. Start the backend again; the tables are created automatically.

On the phone, **Log out** clears the saved login.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| App says "Can't reach the server at http://…:8000" | Backend not running, or the phone can't reach the laptop (step A5). Test by opening `http://<laptop-ip>:8000/health` in the phone's browser; `ipconfig` shows the laptop's IPv4 address. Still blocked? Use the phone hotspot |
| Routes are straight dashed lines | The backend has no road data: `data\roads.pkl` is missing (A4), or the backend was started before the file existed. Restart it and look for `road data ready` |
| "No road route found … outside the area we have maps for" | Pickup or drop is outside the loaded city (Mumbai) |
| "No drivers available right now" / ride never matched | The driver must be online with the app open, within 4 km, the same vehicle type, and must have sent GPS in the last minute |
| `demo.py` says port 8000 is in use | Another backend is running; Ctrl+C it first |
| Driver app opens as the rider app | Make sure you used `npm run start:driver`, not `start:rider` or plain `expo start` |
| Expo Go: "project is incompatible" | Update Expo Go from the store |
| Map is blank or shows "Map tiles failed to load" | The phone has no internet; map tiles are downloaded live |
| Map stuck on Dadar, "Location permission is off" | Allow location for Expo Go in the phone's settings, turn GPS on, and tap **Retry** |
| "This number is registered as a driver/rider" | Each number is one role; use a different number in the other app |
| PowerShell: "running scripts is disabled" | Use `npm.cmd` instead of `npm` |

**Development-mode notes:**
- **The login code is always `123456`**; no SMS is sent.
- **Payment is cash only.**
- **Driver location updates only while the driver app is open**, because background GPS needs a development build.
- **Pickup and drop are chosen by dragging the map.** There's no address search yet.
