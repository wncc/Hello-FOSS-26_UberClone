# Issue 018: Hindi and Marathi translations

**Difficulty:** 🟡 medium · **Area:** mobile · **Skills:** React Native, i18n, Hindi / Marathi

## Why
Many drivers, and many riders, are more comfortable in Hindi or Marathi than English, especially in Mumbai.

## What to do
- Add internationalisation, e.g. `expo-localization` together with `i18next` / `react-i18next`, or a small hand-written translation helper.
- Move every user-facing string into translation files: `en`, `hi`, `mr`.
- Follow the phone's language, and add a language picker on the login screen and in the driver/rider menus.
- Use proper number and currency formatting. `formatFare` already uses Indian digit grouping.

## Where to look
- All screens under `mobile/src/app/` and `mobile/src/components/`.
- `mobile/src/lib/format.ts`: `riderStatusText`, vehicle labels.
- Backend error messages (`detail`) are English. Decide whether the app shows translated messages based on error codes, or keeps English for now.

## Done when
- [ ] Every screen is fully translated in all three languages; native speakers review the wording in the PR.
- [ ] Long translations don't break layouts (check the buttons).
