# deploy/

Configuration for running the routing model on **GraphHopper**, a fast Java routing engine, for production scale. The app doesn't need this to run: development uses the Python router in `routing/`.

| Path | What it is |
|---|---|
| `graphhopper/config.yml` | GraphHopper server config: one profile per vehicle (car, bike, auto rickshaw), turn costs, legal-default speeds |
| `graphhopper/car.json`, `bike.json`, `auto_rickshaw.json` | Per-vehicle models, **generated** from `routing/` by `routing.graphhopper.write_server_models('deploy/graphhopper')`. Don't edit by hand; a test fails if they drift |

What GraphHopper can't do yet (point delays, speed breakers, bike / auto access) is [issue 002](../docs/issues/002-graphhopper-extensions.md). Running GraphHopper in Docker is part of [issue 021](../docs/issues/021-docker-compose.md).
