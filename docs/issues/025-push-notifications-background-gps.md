# Issue 025: Push notifications and background GPS for drivers

**Difficulty:** 🔴 hard · **Area:** mobile + backend · **Skills:** React Native, Expo development builds, notifications

## Why
Drivers must keep the app open on screen to get ride requests and to send their location. Real drivers switch to Google Maps for navigation, which stops both. This is the biggest gap between this app and a real driver app.

## What to do
- **Development build:** Expo Go can't do this; use `npx expo run:android` or an EAS development build. Document the steps.
- **Push:**
  - Register the device for notifications (`expo-notifications`) and save the push token in a new endpoint.
  - When a ride request is sent and the driver's live connection is down, send a push.
  - Tapping the notification opens the request with the remaining countdown.
- **Background location:** `expo-location` background updates with `expo-task-manager` while online, sending to `POST /drivers/me/location`. Show the required ongoing Android notification ("You're online").
- Battery: lower the update rate when the driver isn't on a trip.

## Where to look
- `mobile/src/lib/location.ts`: `useDriverLocationReporter` (foreground only today).
- `backend/app/services/dispatch.py`: where `ride:ping` is sent. `backend/app/services/realtime.py`: `Hub.is_connected`.
- `mobile/app.config.ts`: permissions and plugins.

## Done when
- [ ] With the driver app in the background (Google Maps open), the driver still receives requests and their location keeps updating.
- [ ] Turning off "online" stops background tracking.
