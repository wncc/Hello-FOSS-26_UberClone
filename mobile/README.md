# Rider & driver apps (Expo)

One codebase builds two apps. `EXPO_PUBLIC_APP_VARIANT` picks the variant:

| Variant | Start | What it does |
|---|---|---|
| Rider (default) | `npm run start:rider` | Log in · drag the map to set pickup and drop · compare bike / auto / cab fares · book · watch the driver arrive · share the PIN · rate · ride history |
| Driver | `npm run start:driver` (port 8082) | Log in · vehicle setup · go online (GPS streamed every 4 s) · ride pings with a 20 s countdown · accept / decline · navigate (Google Maps) · arrived · enter the rider's PIN · complete · collect cash · rate · today's earnings |

## Run on a phone

1. Start the backend from the repo root: `uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`.
2. In `mobile/`: `npm install`, then `npm run start:rider` and/or `npm run start:driver`.
3. Scan the QR code with **Expo Go**, with the phone on the same Wi-Fi as the computer.

The app reaches the backend on port 8000 of the computer serving the bundle. Override that with `EXPO_PUBLIC_API_URL=http://<ip>:8000`.

**Logging in (development):** any Indian mobile number works. The backend is in dev mode, so the code is `123456` and the app fills it in for you. A phone number is either a rider or a driver, so use different numbers in the two apps.

**Only one phone?** Simulate the other side from the repo root:

```bash
python -m backend.tools.simulate driver --near 12.9716,77.5946 --vehicle auto_rickshaw   # test the rider app
python -m backend.tools.simulate rider --pickup 12.9716,77.5946 --drop 12.9352,77.6245   # test the driver app
```

The simulated driver must be near where you set the pickup, within 4 km.

## Checks

```bash
npm run typecheck && npm run lint && npm test      # TypeScript, ESLint, Jest (lib logic)
npx expo-doctor
```

## Structure

- `src/app/`: screens (Expo Router). `login`, `name`, `rider/*`, `driver/*`. `Stack.Protected` guards keep each variant on its own screens.
- `src/lib/`: everything that isn't UI:
  - `api.ts`: typed client with automatic token refresh
  - `socket.ts`: live events, with reconnect and backoff
  - `session.tsx`: login state, tokens in SecureStore
  - `rideState.ts`: pure state transitions, unit-tested
  - `location.ts`: GPS, address labels, driver location reporting
  - `format.ts`: ₹ with Indian digit grouping, distances, durations
- `src/components/`: shared UI, the map, and ride history.

## Limits of this version

- **Driver GPS works only while the app is open** (the screen is kept awake while online). Background location and push notifications for pings need a development build (`npx expo run:android`), not Expo Go.
- **Pickup and drop are set by dragging a pin.** There's no address search yet, because that needs a geocoding provider (e.g. Ola Maps or Mappls).
- **Payment is cash only, and the login code is fixed in dev.** Both are intentional for now.
- **Routes follow the roads only if the backend has road data** (`data/roads.pkl`, currently Mumbai; see [docs/BACKEND.md](../docs/BACKEND.md#road-data-routes-that-follow-the-roads)). Without it the map shows a dashed straight placeholder line.
- **Maps are Leaflet in a WebView, with OpenStreetMap tiles.** `react-native-maps` shows a blank map in Expo Go SDK 57 on Android ([expo/expo#49323](https://github.com/expo/expo/issues/49323)). The phone needs internet for the map. The free OSM tile server is fine for testing but not for a launched app: set `EXPO_PUBLIC_MAP_TILE_URL` to a hosted tile provider (MapTiler, Stadia, Ola Maps…) before release.
- **Location problems are shown on screen** (permission off, GPS off, no fix), with a Retry button on the rider home screen.
