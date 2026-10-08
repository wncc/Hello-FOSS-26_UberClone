"""Matching service loop: GET {EXTERNAL_API}/state -> run_cycle -> POST {EXTERNAL_API}/update.

    EXTERNAL_API=http://backend:4000 python -m matching.server [--roads roads.json] [--selection nearest]

Without --roads, pickup distance is straight-line; with it, pickup ETAs come from
the routing engine (per vehicle, with turns, restrictions and point delays).
Cycles never overlap: the next one starts TICK_MS after the previous one started,
or immediately if a cycle ran long.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
import urllib.request
from dataclasses import replace
from datetime import datetime, timezone

from .engine import CycleResult, MatchingConfig, run_cycle
from .eta import EtaProvider

log = logging.getLogger("matching")


def fetch_state(base_url: str, timeout_s: float) -> dict:
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/state", timeout=timeout_s) as resp:
        return json.load(resp)


def push_state(base_url: str, state: dict, timeout_s: float) -> None:
    body = json.dumps({"drivers": state.get("drivers", []), "riders": state.get("riders", [])}).encode()
    req = urllib.request.Request(f"{base_url.rstrip('/')}/update", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s):
        pass


def cycle_once(base_url: str, eta: EtaProvider | None, config: MatchingConfig, timeout_s: float = 5.0) -> CycleResult:
    state = fetch_state(base_url, timeout_s)
    result = run_cycle(state, datetime.now(timezone.utc), eta, config)
    push_state(base_url, result.state, timeout_s)
    return result


def serve(base_url: str, tick_s: float, eta: EtaProvider | None, config: MatchingConfig) -> None:
    while True:
        started = time.monotonic()
        try:
            result = cycle_once(base_url, eta, config)
            log.info("[cycle] %s", " ".join(f"{k}={v}" for k, v in sorted(result.stats.items())))
        except Exception as err:  # keep serving; one bad cycle must not stop matching
            log.error("cycle error: %s", err)
        time.sleep(max(0.0, tick_s - (time.monotonic() - started)))


def _router_eta(roads_path: str) -> EtaProvider:
    from routing import IST, MultiVehicleRouter, TimeBuckets
    from routing.osm_import import load

    from .eta import RouterEta
    return RouterEta(MultiVehicleRouter.local(load(roads_path), buckets=TimeBuckets(IST)))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ride matching service")
    parser.add_argument("--api", default=os.environ.get("EXTERNAL_API", "http://localhost:4000"))
    parser.add_argument("--tick-ms", type=int, default=int(os.environ.get("TICK_MS", "3000")))
    parser.add_argument("--roads", help="roads.json from routing.osm_import, for road-network pickup ETAs")
    parser.add_argument("--selection", choices=("random", "nearest"), default="random")
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config = replace(MatchingConfig(), selection=args.selection)
    eta = _router_eta(args.roads) if args.roads else None
    if args.once:
        print(json.dumps(cycle_once(args.api, eta, config).stats))
    else:
        serve(args.api, args.tick_ms / 1000.0, eta, config)


if __name__ == "__main__":
    main()
