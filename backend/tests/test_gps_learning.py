import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from routing.map_matching import GPSObservation

from app.services.gps_learning import (
    filter_pings_by_phase,
    learn_ride_exposures,
    learn_ride_speeds,
    learn_saved_route_exposures,
    load_phase_pings,
    load_planned_segments,
    load_ride_pings,
    pings_to_observations,
)


START = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def ping(minutes):
    return SimpleNamespace(
        lat=12.9700,
        lng=77.5900,
        recorded_at=START + timedelta(minutes=minutes),
    )


def make_ride(completed=True):
    return SimpleNamespace(
        assigned_at=START,
        arrived_at=START + timedelta(minutes=10),
        started_at=START + timedelta(minutes=15),
        completed_at=(
            START + timedelta(minutes=20)
            if completed else None
        ),
    )


def test_pings_to_observations():
    observations = pings_to_observations([ping(10), ping(0)])

    assert len(observations) == 2
    assert observations[0].recorded_at == START
    assert observations[1].recorded_at == START + timedelta(minutes=10)


def test_load_ride_pings_filters_driver_and_ride():
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result

    pings = asyncio.run(
        load_ride_pings(session, "driver-1", "ride-1")
    )

    assert pings == []
    session.execute.assert_awaited_once()

    sql = str(session.execute.await_args.args[0])
    assert "location_pings.driver_id" in sql
    assert "location_pings.ride_id" in sql
    assert "ORDER BY" in sql


def test_learn_ride_speeds_without_pings():
    session = AsyncMock()

    with patch(
        "app.services.gps_learning.load_phase_pings",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_load:
        samples = asyncio.run(
            learn_ride_speeds(
                session, "driver-1", "ride-1", {}
            )
        )

    assert samples == []
    mock_load.assert_awaited_once_with(
        session, "driver-1", "ride-1", "trip"
    )


def test_learn_ride_exposures():
    observations = [
        GPSObservation(12.9700, 77.5900, START)
    ]

    with (
        patch(
            "app.services.gps_learning.match_gps_sequence",
            return_value=["AB", "BC"],
        ),
        patch(
            "app.services.gps_learning.detect_exposures",
            return_value=[],
        ) as mock_detect,
    ):
        exposures = learn_ride_exposures(
            observations, ["AB", "BD"], {},
            "driver-1", "ride-1",
        )

    assert exposures == []
    mock_detect.assert_called_once()

    arguments = mock_detect.call_args.kwargs
    assert arguments["planned"] == ["AB", "BD"]
    assert arguments["actual"] == ["AB", "BC"]
    assert arguments["driver_id"] == "driver-1"
    assert arguments["trip_id"] == "ride-1"


def test_load_planned_segments():
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = '["AB", "BC"]'
    session.execute.return_value = result

    segments = asyncio.run(
        load_planned_segments(
            session, "driver-1", "ride-1", "trip"
        )
    )

    assert segments == ["AB", "BC"]

    sql = str(session.execute.await_args.args[0])
    assert "planned_routes.driver_id" in sql
    assert "planned_routes.ride_id" in sql
    assert "planned_routes.phase" in sql


def test_learn_saved_route_exposures_without_plan():
    session = AsyncMock()

    with (
        patch(
            "app.services.gps_learning.load_planned_segments",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_planned,
        patch(
            "app.services.gps_learning.load_phase_pings",
            new_callable=AsyncMock,
        ) as mock_pings,
    ):
        exposures = asyncio.run(
            learn_saved_route_exposures(
                session, "driver-1", "ride-1",
                "trip", {},
            )
        )

    assert exposures == []
    mock_planned.assert_awaited_once_with(
        session, "driver-1", "ride-1", "trip"
    )
    mock_pings.assert_not_awaited()


def test_filter_pings_by_phase():
    pings = [ping(i) for i in (0, 5, 10, 15, 20, 25)]

    approach = filter_pings_by_phase(
        pings,
        "approach",
        START + timedelta(minutes=15),
        assigned_at=START,
        arrived_at=START + timedelta(minutes=10),
        completed_at=START + timedelta(minutes=20),
    )

    trip = filter_pings_by_phase(
        pings,
        "trip",
        START + timedelta(minutes=15),
        assigned_at=START,
        arrived_at=START + timedelta(minutes=10),
        completed_at=START + timedelta(minutes=20),
    )

    assert [p.recorded_at for p in approach] == [
        START,
        START + timedelta(minutes=5),
        START + timedelta(minutes=10),
    ]
    assert [p.recorded_at for p in trip] == [
        START + timedelta(minutes=15),
        START + timedelta(minutes=20),
    ]


def test_incomplete_phase_returns_no_pings():
    pings = [ping(0), ping(5)]

    assert filter_pings_by_phase(
        pings,
        "approach",
        assigned_at=START,
        arrived_at=None,
    ) == []

    assert filter_pings_by_phase(
        pings,
        "trip",
        START,
        completed_at=None,
    ) == []


def test_saved_exposures_use_only_trip_pings():
    session = AsyncMock()

    with (
        patch(
            "app.services.gps_learning.load_planned_segments",
            new_callable=AsyncMock,
            return_value=["AB", "BC"],
        ),
        patch(
            "app.services.gps_learning.load_phase_pings",
            new_callable=AsyncMock,
            return_value=[ping(15), ping(20)],
        ),
        patch(
            "app.services.gps_learning.learn_ride_exposures",
            return_value=[],
        ) as mock_exposures,
    ):
        exposures = asyncio.run(
            learn_saved_route_exposures(
                session, "driver-1", "ride-1",
                "trip", {},
            )
        )

    assert exposures == []

    observations = mock_exposures.call_args.args[0]
    assert [p.recorded_at for p in observations] == [
        START + timedelta(minutes=15),
        START + timedelta(minutes=20),
    ]


def test_load_phase_pings_excludes_pickup_waiting():
    session = AsyncMock()

    with (
        patch(
            "app.services.gps_learning.load_ride",
            new_callable=AsyncMock,
            return_value=make_ride(),
        ),
        patch(
            "app.services.gps_learning.load_ride_pings",
            new_callable=AsyncMock,
            return_value=[ping(i) for i in (0, 5, 10, 12, 15, 20, 25)],
        ),
    ):
        approach = asyncio.run(
            load_phase_pings(
                session, "driver-1", "ride-1", "approach"
            )
        )
        trip = asyncio.run(
            load_phase_pings(
                session, "driver-1", "ride-1", "trip"
            )
        )

    assert [p.recorded_at for p in approach] == [
        START + timedelta(minutes=i)
        for i in (0, 5, 10)
    ]
    assert [p.recorded_at for p in trip] == [
        START + timedelta(minutes=i)
        for i in (15, 20)
    ]


def test_incomplete_trip_does_not_generate_speeds():
    session = AsyncMock()

    with (
        patch(
            "app.services.gps_learning.load_ride",
            new_callable=AsyncMock,
            return_value=make_ride(completed=False),
        ),
        patch(
            "app.services.gps_learning.load_ride_pings",
            new_callable=AsyncMock,
        ) as mock_pings,
    ):
        samples = asyncio.run(
            learn_ride_speeds(
                session, "driver-1", "ride-1", {}
            )
        )

    assert samples == []
    mock_pings.assert_not_awaited()


def test_speed_extraction_receives_only_phase_pings():
    session = AsyncMock()
    phase_pings = [ping(15), ping(20)]

    with (
        patch(
            "app.services.gps_learning.load_phase_pings",
            new_callable=AsyncMock,
            return_value=phase_pings,
        ),
        patch(
            "app.services.gps_learning.extract_speed_samples",
            return_value=[],
        ) as mock_extract,
    ):
        samples = asyncio.run(
            learn_ride_speeds(
                session, "driver-1", "ride-1", {}
            )
        )

    assert samples == []
    mock_extract.assert_called_once()

    observations = mock_extract.call_args.args[0]
    assert [p.recorded_at for p in observations] == [
        START + timedelta(minutes=15),
        START + timedelta(minutes=20),
    ]



def test_validated_exposures_reject_unverified_deviation():
    from app.services.gps_learning import validated_ride_exposures
    from routing.models import EdgeMeta
    from routing import RoadClass
    edges = {
        "AB": EdgeMeta("AB", "A", "B", RoadClass.RESIDENTIAL, 100),
        "BC": EdgeMeta("BC", "B", "C", RoadClass.RESIDENTIAL, 100),
        "BD": EdgeMeta("BD", "B", "D", RoadClass.RESIDENTIAL, 100),
    }
    points = [GPSObservation(12.97, 77.59, START + timedelta(seconds=i * 10)) for i in range(3)]
    with patch("app.services.gps_learning.match_gps_sequence", return_value=["AB", "BD"]):
        exposures = validated_ride_exposures(points, ["AB", "BC"], edges, "d", "r")
    assert [e.segment_id for e in exposures] == ["AB"]
    assert all(e.followed for e in exposures)


def test_unverified_deviation_is_not_avoided():
    """GPS jumps without a confirmed alternative path are not avoidance."""
    from datetime import datetime, timedelta, timezone
    from routing.map_matching import GPSObservation
    from app.services.gps_learning import validated_ride_exposures

    now = datetime(2026, 10, 21, tzinfo=timezone.utc)

    observations = [
        GPSObservation(
            lat=19.0,
            lng=72.0,
            recorded_at=now + timedelta(seconds=i * 10),
        )
        for i in range(6)
    ]

    result = validated_ride_exposures(
        observations=observations,
        planned_segments=["a", "b", "c", "d"],
        edges={},
        driver_id="driver-1",
        ride_id="ride-1",
    )

    assert not any(not event.followed for event in result)


def test_validated_exposures_detects_confirmed_detour():
    from unittest.mock import patch
    from datetime import datetime, timedelta, timezone

    from routing import RoadClass
    from routing.models import EdgeMeta
    from routing.map_matching import GPSObservation

    from app.services.gps_learning import validated_ride_exposures

    edges = {
        "AB": EdgeMeta("AB", "A", "B", RoadClass.RESIDENTIAL, 100),
        "BC": EdgeMeta("BC", "B", "C", RoadClass.RESIDENTIAL, 100),
        "CD": EdgeMeta("CD", "C", "D", RoadClass.RESIDENTIAL, 100),
        "DE": EdgeMeta("DE", "D", "E", RoadClass.RESIDENTIAL, 100),
        "BX": EdgeMeta("BX", "B", "X", RoadClass.RESIDENTIAL, 100),
        "XY": EdgeMeta("XY", "X", "Y", RoadClass.RESIDENTIAL, 100),
        "YD": EdgeMeta("YD", "Y", "D", RoadClass.RESIDENTIAL, 100),
    }

    # A -> B -> X -> Y -> D -> E instead of
    # A -> B -> C -> D -> E.
    actual = ["AB", "BX", "XY", "YD", "DE"]
    planned = ["AB", "BC", "CD", "DE"]

    # Need two followed segments before deviation, so use a
    # separate preceding segment.
    edges["ZA"] = EdgeMeta(
        "ZA", "Z", "A", RoadClass.RESIDENTIAL, 100
    )
    actual.insert(0, "ZA")
    planned.insert(0, "ZA")

    now = datetime(2026, 10, 21, tzinfo=timezone.utc)

    points = [
        GPSObservation(19.0, 72.0, now + timedelta(seconds=i * 10))
        for i in range(len(actual) * 2)
    ]

    groups = [
        (seg, points[i * 2:i * 2 + 2])
        for i, seg in enumerate(actual)
    ]

    with (
        patch(
            "app.services.gps_learning.match_gps_sequence",
            return_value=actual,
        ),
        patch(
            "app.services.gps_learning.group_observations_by_segment",
            return_value=groups,
        ),
    ):
        result = validated_ride_exposures(
            points, planned, edges, "driver", "ride"
        )

    assert [(e.segment_id, e.followed) for e in result] == [
        ("ZA", True),
        ("AB", True),
        ("BC", False),
    ]


def test_validated_exposures_rejects_gps_gap_during_detour():
    from unittest.mock import patch
    from datetime import datetime, timedelta, timezone

    from routing import RoadClass
    from routing.models import EdgeMeta
    from routing.map_matching import GPSObservation

    from app.services.gps_learning import validated_ride_exposures

    edges = {
        "ZA": EdgeMeta("ZA", "Z", "A", RoadClass.RESIDENTIAL, 100),
        "AB": EdgeMeta("AB", "A", "B", RoadClass.RESIDENTIAL, 100),
        "BC": EdgeMeta("BC", "B", "C", RoadClass.RESIDENTIAL, 100),
        "CD": EdgeMeta("CD", "C", "D", RoadClass.RESIDENTIAL, 100),
        "DE": EdgeMeta("DE", "D", "E", RoadClass.RESIDENTIAL, 100),
        "BX": EdgeMeta("BX", "B", "X", RoadClass.RESIDENTIAL, 100),
        "XY": EdgeMeta("XY", "X", "Y", RoadClass.RESIDENTIAL, 100),
        "YD": EdgeMeta("YD", "Y", "D", RoadClass.RESIDENTIAL, 100),
    }

    actual = ["ZA", "AB", "BX", "XY", "YD", "DE"]
    planned = ["ZA", "AB", "BC", "CD", "DE"]

    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    points = [
        GPSObservation(19.0, 72.0, now + timedelta(seconds=i * 10))
        for i in range(len(actual) * 2)
    ]

    groups = [
        (seg, points[i * 2:i * 2 + 2])
        for i, seg in enumerate(actual)
    ]
    groups.insert(3, (None, []))

    with (
        patch(
            "app.services.gps_learning.match_gps_sequence",
            return_value=actual,
        ),
        patch(
            "app.services.gps_learning.group_observations_by_segment",
            return_value=groups,
        ),
    ):
        result = validated_ride_exposures(
            points, planned, edges, "driver", "ride"
        )

    assert [e.segment_id for e in result] == ["ZA", "AB"]
    assert all(e.followed for e in result)
