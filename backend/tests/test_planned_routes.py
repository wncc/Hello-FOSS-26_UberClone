import json
import sqlite3
import dataclasses

from .conftest import driver, rider, tick
from backend.app.services.routes import RouteService
from routing import (
    EdgeMeta,
    LocalAStarRouter,
    MultiVehicleRouter,
    RoadClass,
    RoadGraph,
    RoutingService,
    VehicleType,
)
from routing.graph import haversine_m


NODES = {
    "A": (12.9700, 77.5900),
    "B": (12.9725, 77.5950),
    "C": (12.9700, 77.6000),
}


def make_test_routes():
    edges = [
        EdgeMeta(
            segment_id=segment_id,
            from_node=start,
            to_node=end,
            road_class=RoadClass.PRIMARY,
            distance_m=haversine_m(NODES[start], NODES[end]),
            geometry=(NODES[start], NODES[end]),
        )
        for segment_id, start, end in [
            ("AB", "A", "B"),
            ("BC", "B", "C"),
        ]
    ]

    service = RoutingService(
        LocalAStarRouter(RoadGraph(NODES, edges)),
        {edge.segment_id: edge for edge in edges},
    )
    routes = RouteService(MultiVehicleRouter({VehicleType.CAR: service}))

    return routes

def test_route_estimate_includes_segments():
    routes = make_test_routes()
    estimate = routes.estimate(NODES["A"], NODES["C"], VehicleType.CAR)

    assert estimate is not None
    assert estimate.segment_ids == ["AB", "BC"]


def test_planned_routes_saved_on_assignment_and_start(client, tmp_path):
    # Use our small road network instead of the default no-road setup.
    client.app.state.ctx.routes = make_test_routes()

    client.app.state.ctx.settings = dataclasses.replace(
        client.app.state.ctx.settings, run_gps_learning_loop=True
    )

    passenger = rider(client)
    assigned_driver = driver(client, *NODES["A"])

    response = passenger.post(
        "/rides",
        {
            "pickup": {
                "lat": NODES["B"][0],
                "lng": NODES["B"][1],
                "address": "Point B",
            },
            "drop": {
                "lat": NODES["C"][0],
                "lng": NODES["C"][1],
                "address": "Point C",
            },
            "vehicle_type": "car",
        },
    )
    assert response.status_code == 201, response.text
    ride = response.json()
    ride_id = ride["id"]

    # Driver receives and accepts the offer.
    tick(client)
    assert assigned_driver.post(f"/rides/{ride_id}/accept").status_code == 202
    tick(client)

    assigned = passenger.get(f"/rides/{ride_id}").json()
    assert assigned["status"] == "driver_assigned"

    def saved_routes():
        with sqlite3.connect(tmp_path / "test0.db") as connection:
            return connection.execute(
                """
                SELECT phase, driver_id, segment_ids
                FROM planned_routes
                WHERE ride_id = ?
                ORDER BY phase
                """,
                (ride_id,),
            ).fetchall()

    # Assignment should save the route from A to B.
    records = saved_routes()
    assert len(records) == 1
    assert records[0][0] == "approach"
    assert records[0][1] == assigned_driver.id
    assert json.loads(records[0][2]) == ["AB"]

    # Starting the trip should save the route from B to C.
    assert assigned_driver.post(f"/rides/{ride_id}/arrived").status_code == 200

    started = assigned_driver.post(
        f"/rides/{ride_id}/start",
        {"pin": ride["pin"]},
    )
    assert started.status_code == 200, started.text

    records = saved_routes()
    assert len(records) == 2

    by_phase = {
        phase: json.loads(segment_ids)
        for phase, _, segment_ids in records
    }
    assert by_phase == {
        "approach": ["AB"],
        "trip": ["BC"],
    }
