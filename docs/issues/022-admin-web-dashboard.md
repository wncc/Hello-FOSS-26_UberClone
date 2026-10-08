# Issue 022: Admin web dashboard

**Difficulty:** 🟡 medium (can be split into smaller pull requests) · **Area:** new web app · **Skills:** React / TypeScript, maps

## Why
Admin features exist only as API endpoints. Operations staff need a screen to approve drivers and watch what's happening.

## What to do
Create an `admin/` web app (React + Vite + TypeScript) using the existing admin APIs:
1. **Login** with the OTP flow, as a number listed in `ADMIN_PHONES`.
2. **Drivers:** a list filtered by status (pending / approved / suspended), with Approve and Suspend buttons.
3. **Rides:** a list of recent rides with status, vehicle, fare and times, and a filter by status.
4. **Live map:** online drivers and active rides on a Leaflet map. You'll need a new admin endpoint for driver positions.

## Where to look
- `backend/app/api/admin.py`: existing endpoints.
- `mobile/src/components/map/mapPage.ts`: Leaflet setup you can reuse.
- `backend/app/config.py`: `admin_phones`, `auto_approve_drivers` (set it to `false` to test approvals).

## Done when
- [ ] An admin can approve a pending driver, who can then go online.
- [ ] The live map updates at least every 10 seconds.
- [ ] Non-admins can't use it (the backend already refuses them; the UI should say so clearly).
