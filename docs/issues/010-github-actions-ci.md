# Issue 010: Run the tests automatically on every pull request (GitHub Actions)

**Difficulty:** 🟢 good first issue · **Area:** DevOps · **Skills:** YAML, GitHub Actions

## Why
During the event many people will send pull requests at once. Tests that run automatically catch breakages before anyone reviews.

## What to do
- Add `.github/workflows/tests.yml`, running on every push and pull request:
  1. Python 3.13: `pip install -r requirements-dev.txt`, then `python -m pytest -q`.
  2. Node 24: `npm ci` in `mobile/`, then `npx tsc --noEmit`, `npx eslint src app.config.ts metro.config.js` and `npx jest`.
- Cache pip and npm downloads so runs are fast.
- Optional second job: the browser end-to-end test (`python e2e/run_e2e.py`). It needs `python -m playwright install --with-deps chromium`. It also needs road data, so either skip it in CI or build a small road file for a tiny area. Upload `e2e/report/` as an artifact.

## Where to look
- `test_all.py`: the same checks, as run locally.
- `RUNNING.md`, section F.

## Done when
- [ ] A pull request shows a green check when the tests pass and a red one when they fail (prove it with a deliberately broken test in a draft PR).
