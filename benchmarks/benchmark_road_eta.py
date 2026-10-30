import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from matching import RouterEta
from routing import (
    CAR,
    EdgeMeta,
    LocalAStarRouter,
    MultiVehicleRouter,
    RoadClass,
    RoadGraph,
    RoutingService,
    VehicleType,
)
from routing.graph import haversine_m

# Synthetic two-way road grid. This is a benchmark, not Mumbai road data.
GRID_SIZE = 60
SPACING = 0.001
RUNS = 15
NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def build_router():
    nodes = {
        f"{r}_{c}": (19.0 + r * SPACING, 72.9 + c * SPACING)
        for r in range(GRID_SIZE)
        for c in range(GRID_SIZE)
    }

    edges = []

    def add_edge(a, b):
        edges.append(
            EdgeMeta(
                f"{a}->{b}",
                a,
                b,
                RoadClass.PRIMARY,
                haversine_m(nodes[a], nodes[b]),
                geometry=(nodes[a], nodes[b]),
            )
        )

    for r in range(GRID_SIZE):
        for c in range(GRID_SIZE):
            here = f"{r}_{c}"
            if r + 1 < GRID_SIZE:
                there = f"{r + 1}_{c}"
                add_edge(here, there)
                add_edge(there, here)
            if c + 1 < GRID_SIZE:
                there = f"{r}_{c + 1}"
                add_edge(here, there)
                add_edge(there, here)

    edge_map = {edge.segment_id: edge for edge in edges}
    graph = RoadGraph(nodes, edges)
    service = RoutingService(
        LocalAStarRouter(graph), edge_map, profile=CAR
    )
    router = MultiVehicleRouter({VehicleType.CAR: service})
    return router, graph, service


def main():
    print(f"Building {GRID_SIZE}x{GRID_SIZE} road grid...")
    start = time.perf_counter()
    router, graph, service = build_router()
    print(
        f"Graph built in {(time.perf_counter() - start) * 1000:.1f} ms"
    )
    print(f"Nodes: {len(graph.nodes):,}; directed edges: {len(graph.edges):,}")

    eta = RouterEta(router)
    backend = service.backend
    original_reverse = backend.reverse_costs
    reverse_times_ms = []

    def timed_reverse(*args, **kwargs):
        start = time.perf_counter()
        try:
            return original_reverse(*args, **kwargs)
        finally:
            reverse_times_ms.append(
                (time.perf_counter() - start) * 1000
            )

    backend.reverse_costs = timed_reverse

    rider = graph.nodes[f"{GRID_SIZE // 2}_{GRID_SIZE // 2}"]
    driver_nodes = [
        (5, 5), (5, 25), (5, 45),
        (20, 10), (20, 50),
        (40, 8), (40, 48),
        (54, 15), (54, 30), (54, 50),
    ]
    drivers = {
        f"driver_{i}": graph.nodes[f"{r}_{c}"]
        for i, (r, c) in enumerate(driver_nodes)
    }

    total_times_ms = []

    # Warm-up, then collect repeatable measurements.
    for run in range(RUNS + 2):
        reverse_times_ms.clear()
        start = time.perf_counter()
        results = eta.pickup_etas_s(
            drivers, rider, VehicleType.CAR, NOW
        )
        total_ms = (time.perf_counter() - start) * 1000

        if run >= 2:
            total_times_ms.append(total_ms)

        if len(results) != len(drivers):
            raise RuntimeError("Some driver ETA results are missing")
        if not any(value is not None for value in results.values()):
            raise RuntimeError("No driver received a valid ETA")

        if run == RUNS + 1:
            print(f"Valid ETA results: {sum(v is not None for v in results.values())}/{len(drivers)}")

    reverse_ms = reverse_times_ms[-1] if reverse_times_ms else float("nan")
    print(f"\nFull batch ETA median: {statistics.median(total_times_ms):.2f} ms")
    print(f"Full batch ETA slowest: {max(total_times_ms):.2f} ms")
    print(f"Reverse search (last run): {reverse_ms:.2f} ms")


if __name__ == "__main__":
    main()
