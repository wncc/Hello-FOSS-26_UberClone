# Contributing

Thanks for helping! This guide gets you from "I want to help" to a merged pull request.

## 1. Get it running

Follow [RUNNING.md](RUNNING.md): case **A** (first-time setup), then case **B** to see a whole ride on your phone. If you don't have a phone handy, case **E** runs everything in the browser. The [overview](docs/OVERVIEW.md) explains how the pieces fit together.

## 2. Pick an issue

The open issues are listed in the [README](README.md#open-issues), grouped by difficulty: 🟢 good first, 🟡 medium, 🔴 hard. Each one says what to do, which files to look at, and how to know you're done.

- **New to the project?** Start with a 🟢 issue.
- **Claim it before you start.** Tell the organisers, or comment on the GitHub issue, so two people don't build the same thing.
- **Big issues can be split.** For example, issue 022 (admin dashboard) can be "driver list" first and "live map" later. Say which part you're taking.
- **Have your own idea?** Open a discussion or a new issue first (see section 6).

## 3. Make the change

```powershell
git checkout -b issue-012-place-search
```

Follow the code around you:

| Part | Conventions |
|---|---|
| Python (`backend/`, `routing/`, `matching/`) | Type hints everywhere; small functions; dataclasses for data; comments only where the *why* isn't obvious; no new dependency without a good reason |
| Backend API | Request and response models in `backend/app/schemas.py`; rules and state changes in `backend/app/services/`, not in the route handlers; domain errors via `DomainError` |
| Apps (`mobile/`) | TypeScript strict mode; screens in `src/app/` (Expo Router), everything else in `src/lib/` and `src/components/`; plain logic (no React) goes in `src/lib/` so it can be unit-tested; install packages with `npx expo install <package>` |
| Money and units | Fares in **paise** (integers), distances in **metres**, durations in **seconds**, times in **UTC** (convert to IST only for display or time-of-day logic) |

**Changing the database:** there are no migrations yet ([issue 020](docs/issues/020-database-migrations-postgres.md)). If you add a column, say so in your pull request; everyone needs to delete their local `uberclone.db`.

## 4. Test it

Every change comes with tests. Each issue says which test file to extend.

```powershell
python test_all.py --quick    # Python tests, app typecheck, lint, app unit tests (~30 s)
python test_all.py            # + the browser robot playing a full ride (~3-5 min)
```

| What you changed | Where to add tests |
|---|---|
| Routing or matching | `tests/` (pytest) |
| Backend API | `backend/tests/test_api.py` (pytest, uses a temporary database) |
| App logic in `mobile/src/lib/` | `mobile/src/lib/__tests__/` (Jest) |
| A user-visible flow | `e2e/run_e2e.py` (a step with a screenshot) |

If you changed anything visual, run the full `python test_all.py` and look at `e2e/report/index.html`. It's also worth trying on a real phone (`python demo.py`).

## 5. Open a pull request

- **Title:** the issue number and a short summary, e.g. `#012 Place search for pickup and drop`.
- **Description:** what you changed, how you tested it, and **screenshots** for anything visual.
- **Keep it focused:** one issue per pull request. Unrelated clean-ups go in their own PR.
- **Checks:** `python test_all.py --quick` must pass.

## 6. Writing a new issue

Copy the shape of the existing ones in `docs/issues/`. Then add a row to the right difficulty table in the [README](README.md#open-issues).

```markdown
# Issue NNN: Short title saying what users get

**Difficulty:** 🟢 good first issue | 🟡 medium | 🔴 hard · **Area:** … · **Skills:** …

## Why
The problem, from a rider's, driver's or developer's point of view.

## What to do
Concrete steps. Leave design freedom where it doesn't matter.

## Where to look
The files and functions to start from.

## Done when
- [ ] Checkable outcomes, including tests.
```

## Be kind

Be welcoming and patient. Review code, not people. Ask questions in the open; if something confused you, it probably confuses others too. Improving the docs is a great contribution.
