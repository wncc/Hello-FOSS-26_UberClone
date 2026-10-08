# Issue 021: One-command local setup with Docker Compose

**Difficulty:** 🟡 medium · **Area:** DevOps · **Skills:** Docker

## Why
Setting up Python, Node, the road data and (later) PostgreSQL and Redis by hand takes time. That's painful at a hackathon where everyone starts at once.

## What to do
- A `Dockerfile` for the backend, and a `docker-compose.yml` with:
  - the backend (port 8000);
  - PostgreSQL, once issue 020 lands; until then, SQLite on a volume;
  - a one-time "roads" service that downloads the OSM extract and builds `data/roads.pkl` into a shared volume if it's missing.
- Optional: a GraphHopper service using `deploy/graphhopper/config.yml` and the generated vehicle model files.
- Update `RUNNING.md` with a "Docker" case.

## Where to look
- `RUNNING.md`, section A (manual setup).
- `deploy/graphhopper/`.

## Done when
- [ ] `docker compose up` on a fresh machine gives a backend with road data, reachable from a phone on the same Wi-Fi.
- [ ] Rebuilding doesn't download the 221 MB extract again.
