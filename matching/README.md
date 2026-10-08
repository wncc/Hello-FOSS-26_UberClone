# matching/

Decides **which drivers get each ride request, and who wins**. Pure logic: the backend calls `run_cycle` every 3 seconds with the current drivers and waiting riders. Full documentation: [docs/MATCHING.md](../docs/MATCHING.md).

| File | What it is |
|---|---|
| `engine.py` | `run_cycle(state, now, eta, config)`. It resolves acceptances (nearest wins), releases expired or stale pings, and pings up to 3 nearby drivers of the right vehicle per rider |
| `eta.py` | Pickup-time providers: straight-line, or road-based via the routing engine |
| `geo.py` | Distance and a grid index for finding nearby drivers |
| `server.py` | Optional stand-alone service using the original `/state` and `/update` HTTP contract (the backend doesn't need it) |

Tests: `tests/test_matching.py`. This is a Python port of `ride-matching-engine-uber-main/` (Node), with its bugs fixed.
