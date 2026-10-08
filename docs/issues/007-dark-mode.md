# Issue 007: Dark mode for both apps

**Difficulty:** 🟢 good first issue · **Area:** mobile · **Skills:** React Native, design

## Why
Drivers use the app at night for hours; a bright white screen is tiring and drains battery.

## What to do
- Follow the phone's light/dark setting (`useColorScheme()` from React Native).
- Define a dark palette next to the light one and use it everywhere.
- Use a dark map style in dark mode too. Leaflet can use a dark tile layer, or a CSS filter on the tile pane as a quick start.
- Make the status bar readable in both modes.

## Where to look
- `mobile/src/components/ui.tsx`: `colors` is currently one fixed light palette used across the app.
- `mobile/src/components/map/mapPage.ts`: the map page (tile URL / CSS).
- `mobile/src/app/_layout.tsx`: `StatusBar style="dark"`.

## Done when
- [ ] Every screen is readable in dark mode: login, name, rider home, ride, history, driver home, vehicle, trip.
- [ ] Switching the phone's theme updates the app.
- [ ] Screenshots of a few screens in both modes are attached to the pull request.
