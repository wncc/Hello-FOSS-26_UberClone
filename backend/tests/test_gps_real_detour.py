
from datetime import datetime, timedelta, timezone

from routing import RoadClass
from routing.models import EdgeMeta
from routing.map_matching import GPSObservation

from app.services.gps_learning import validated_ride_exposures


def test_real_gps_detour():
    # Road coordinates: (latitude, longitude)
    nodes = {
        "Z": (19.0000, 72.0000),
        "A": (19.0000, 72.0010),
        "B": (19.0000, 72.0020),
        "C": (19.0000, 72.0030),
        "D": (19.0000, 72.0040),
        "E": (19.0000, 72.0050),
        "X": (19.0010, 72.0020),
        "Y": (19.0010, 72.0040),
    }

    def edge(name, start, end):
        return EdgeMeta(
            name,
            start,
            end,
            RoadClass.RESIDENTIAL,
            100,
            geometry=(nodes[start], nodes[end]),
        )

    edges = {
        name: edge(name, name[0], name[1])
        for name in [
            "ZA", "AB", "BC", "CD", "DE",
            "BX", "XY", "YD",
        ]
    }

    planned = ["ZA", "AB", "BC", "CD", "DE"]
    actual = ["ZA", "AB", "BX", "XY", "YD", "DE"]

    now = datetime(2026, 10, 21, tzinfo=timezone.utc)

    # Two GPS observations inside each actual road.
    points = []

    for name in actual:
        start = nodes[name[0]]
        end = nodes[name[1]]

        for fraction in (0.3, 0.7):
            points.append(
                GPSObservation(
                    lat=start[0] + fraction * (end[0] - start[0]),
                    lng=start[1] + fraction * (end[1] - start[1]),
                    recorded_at=now + timedelta(
                        seconds=len(points) * 10
                    ),
                )
            )

    exposures = validated_ride_exposures(
        points,
        planned,
        edges,
        "driver-1",
        "ride-1",
    )

    assert [
        (event.segment_id, event.followed)
        for event in exposures
    ] == [
        ("ZA", True),
        ("AB", True),
        ("BC", False),
    ]
