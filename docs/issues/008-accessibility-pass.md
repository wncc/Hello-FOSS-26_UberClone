# Issue 008: Accessibility: screen-reader labels and touch targets

**Difficulty:** 🟢 good first issue · **Area:** mobile · **Skills:** React Native, accessibility

## Why
People using TalkBack (Android) or VoiceOver (iPhone) can't use parts of the app today. Some tappable things aren't announced as buttons, and some are too small.

## What to do
- Make every tappable element a button with a clear label. The top chips (**Rides**, **Log out**, **Earnings**, **Vehicle**) are plain `Text` / `Pressable` without `accessibilityRole="button"`.
- Give the map an accessible description, and make sure the pickup / drop text in the bottom panel is read out.
- Make touch targets at least 44×44 points.
- Announce important changes (e.g. "Driver has arrived") using `AccessibilityInfo.announceForAccessibility`.

## Where to look
- `mobile/src/app/rider/index.tsx` (`Chip`), `mobile/src/app/driver/index.tsx` (chips in the top bar), the vehicle choices in `mobile/src/app/driver/vehicle.tsx`, the star ratings in the ride / trip screens.
- `mobile/src/components/ui.tsx`: shared components.

## Done when
- [ ] With TalkBack or VoiceOver on, a full booking can be completed without looking at the screen.
- [ ] The e2e test still passes. It finds buttons by role, so this should even make it stricter.
