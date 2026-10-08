# Documentation map

Start with **[OVERVIEW.md](OVERVIEW.md)**, then read whatever matches what you're working on.

## Start here

| Document | Read it to… |
|---|---|
| [OVERVIEW.md](OVERVIEW.md) | Understand what the app is, its pieces, and what happens during a ride |
| [../RUNNING.md](../RUNNING.md) | Run it: setup, phone demo, two phones, browser, tests, another city, troubleshooting |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Contribute: pick an issue, conventions, tests, pull requests |
| [../README.md#open-issues](../README.md#open-issues) | See the open issues by difficulty (the issue files themselves are in [issues/](issues/)) |

## By part of the system

| Document | Covers |
|---|---|
| [BACKEND.md](BACKEND.md) | The API, live events, settings (environment variables), road data loading, backend rules (PIN, timeouts, roles) |
| [MATCHING.md](MATCHING.md) | How drivers are pinged and chosen; bugs fixed from the original Node engine |
| [../mobile/README.md](../mobile/README.md) | The rider and driver apps: running them, structure, limits |
| [TESTING.md](TESTING.md) | Every kind of test, the browser robot and its report, the phone demo |

## Routing engine (in depth)

| Document | Covers |
|---|---|
| [ROUTING.md](ROUTING.md) | The core idea: cost = distance ÷ (speed × priority), the road hierarchy, telemetry rules and their guardrails |
| [VEHICLES_AND_TURNS.md](VEHICLES_AND_TURNS.md) | Car / auto / bike rules, turn costs (left-hand traffic), waits at signals and toll booths, speed breakers |
| [MAP_DATA.md](MAP_DATA.md) | Importing OpenStreetMap: speed limits, private roads, tolls, time-based closures, restricted zones |
| [ROAD_LEARNING.md](ROAD_LEARNING.md) | Learning slow roads (traffic vs road condition) and avoided roads from driver GPS |

## Plans and history

| Document | Covers |
|---|---|
| [PLAN.md](PLAN.md) | The original build plan and phases (what's done, what was deferred) |
| [issues/001-eta-approximation.md](issues/001-eta-approximation.md), [issues/002-graphhopper-extensions.md](issues/002-graphhopper-extensions.md) | The first two design issues, kept in the issue list |

## Folder guide

| Folder | What's inside | Its README |
|---|---|---|
| `mobile/` | Rider and driver apps | [mobile/README.md](../mobile/README.md) |
| `backend/` | API, dispatch loop, simulator | [backend/README.md](../backend/README.md) |
| `matching/` | Matching engine | [matching/README.md](../matching/README.md) |
| `routing/` | Routing engine | [routing/README.md](../routing/README.md) |
| `tests/` | Routing and matching tests | — |
| `e2e/` | Browser robot test | [e2e/README.md](../e2e/README.md) |
| `deploy/` | GraphHopper configuration | [deploy/README.md](../deploy/README.md) |
| `schemas/` | Example JSON for road data, telemetry and rules | — |
| `ride-matching-engine-uber-main/` | The original Node matching engine (reference only; the Python port in `matching/` is what runs) | its own README |
