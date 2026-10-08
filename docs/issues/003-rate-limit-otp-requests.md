# Issue 003: Rate-limit OTP requests

**Difficulty:** 🟢 good first issue · **Area:** backend, security · **Skills:** Python, FastAPI

## Why
`POST /auth/otp/request` can be called any number of times for any phone number. Once real SMS is switched on, that costs money and lets someone flood a stranger's phone with codes.

## What to do
- Allow at most **3 OTP requests per phone number per 10 minutes**, and **20 per IP address per hour**.
- When over the limit, return **429** with a message saying when to try again (e.g. "Too many codes requested. Try again in 7 minutes.").
- Keep the limits in `Settings`, so they can be changed without code changes.

## Where to look
- `backend/app/api/auth.py`: `request_otp`.
- `backend/app/models.py`: `OtpCode` already stores one row per phone; you may need a request counter or a small table of request times.
- `backend/app/config.py`: add the limits.

## Done when
- [ ] The 4th request for the same number within 10 minutes returns 429 with a clear message.
- [ ] A new test in `backend/tests/test_api.py` covers the limit, and the limit resetting after the window (inject the time instead of sleeping).
- [ ] `python test_all.py --quick` passes.
