
from datetime import datetime, timedelta, timezone

from routing import EdgeMeta, RoadClass
from routing.map_matching import (
    GPSObservation,
    complete_traversal,
    extract_speed_samples,
    group_observations_by_segment,
    match_gps_sequence,
    nearest_segment,
    segment_progress,
    speed_sample_from_observations,
    traversal_speed_kmh,
)


START = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def edge(segment_id, from_node, to_node, start_lng, end_lng):
    return EdgeMeta(
        segment_id,
        from_node,
        to_node,
        RoadClass.RESIDENTIAL,
        100,
        geometry=(
            (12.9700, start_lng),
            (12.9700, end_lng),
        ),
    )


def roads():
    return {
        "AB": edge("AB", "A", "B", 77.5900, 77.5910),
        "BC": edge("BC", "B", "C", 77.5910, 77.5920),
    }


def point(lng, seconds, lat=12.9700):
    return GPSObservation(
        lat, lng, START + timedelta(seconds=seconds)
    )


def test_nearest_segment():
    edges = {"AB": roads()["AB"]}

    assert nearest_segment(
        (12.97001, 77.5905), edges
    ) == "AB"

    assert nearest_segment(
        (13.0000, 77.6000), edges
    ) is None


def test_match_gps_sequence():
    points = [
        (12.9700, 77.5902),
        (12.9700, 77.5908),
        (12.9700, 77.5912),
        (12.9700, 77.5918),
    ]

    assert match_gps_sequence(
        points, roads()
    ) == ["AB", "BC"]


def test_gps_gap_breaks_sequence():
    points = [
        (12.9700, 77.5902),
        (12.9700, 77.5908),
        (13.0000, 77.6000),
        (12.9700, 77.5912),
        (12.9700, 77.5918),
    ]

    assert match_gps_sequence(points, roads()) == ["BC"]


def test_segment_progress():
    start = (12.9700, 77.5900)
    end = (12.9700, 77.5910)

    assert segment_progress(start, start, end) == 0.0
    assert segment_progress(end, start, end) == 1.0
    assert abs(
        segment_progress(
            (12.9700, 77.5905), start, end
        ) - 0.5
    ) < 0.01


def test_complete_traversal_boundaries():
    assert complete_traversal(0.05, 0.95)
    assert not complete_traversal(0.40, 0.95)
    assert not complete_traversal(0.05, 0.70)
    assert not complete_traversal(0.95, 0.05)


def test_traversal_speed_validation():
    assert traversal_speed_kmh(
        100, START, START + timedelta(seconds=20)
    ) == 18.0

    assert traversal_speed_kmh(
        100, START, START - timedelta(seconds=20)
    ) is None

    assert traversal_speed_kmh(
        100, START, START + timedelta(minutes=10)
    ) is None

    assert traversal_speed_kmh(
        1000, START, START + timedelta(seconds=1)
    ) is None


def test_speed_sample_from_observations():
    observations = [
        point(77.59002, 0),
        point(77.59050, 10),
        point(77.59098, 20),
    ]

    sample = speed_sample_from_observations(
        observations,
        roads()["AB"],
        "driver-1",
        "trip-1",
    )

    assert sample is not None
    assert sample.segment_id == "AB"
    assert sample.driver_id == "driver-1"
    assert sample.trip_id == "trip-1"
    assert sample.speed_kmh == 18.0


def test_reject_unreliable_speed_samples():
    cases = {
        "incomplete_start": [
            point(77.59050, 0),
            point(77.59098, 20),
        ],
        "incomplete_end": [
            point(77.59002, 0),
            point(77.59050, 20),
        ],
        "gps_jump": [
            point(77.59002, 0),
            point(77.59098, 1),
        ],
        "gps_gap": [
            point(77.59002, 0),
            point(77.59098, 120),
        ],
        "wrong_direction": [
            point(77.59002, 0),
            point(77.59080, 10),
            point(77.59040, 15),
            point(77.59098, 25),
        ],
    }

    for name, observations in cases.items():
        sample = speed_sample_from_observations(
            observations,
            roads()["AB"],
            "driver-1",
            "trip-1",
        )

        assert sample is None, f"Should reject {name}"


def test_group_gps_observations():
    observations = [
        point(77.5902, 0),
        point(77.5908, 10),
        point(77.5912, 20),
        point(77.5918, 30),
    ]

    groups = group_observations_by_segment(
        observations, roads()
    )

    assert [segment_id for segment_id, _ in groups] == [
        "AB", "BC"
    ]
    assert [len(points) for _, points in groups] == [2, 2]


def test_group_observations_preserves_gps_gap():
    observations = [
        point(77.5902, 0),
        point(77.6000, 10, lat=13.0000),
        point(77.5908, 20),
    ]

    groups = group_observations_by_segment(
        observations, {"AB": roads()["AB"]}
    )

    assert [segment_id for segment_id, _ in groups] == [
        "AB", None, "AB"
    ]
    assert [len(points) for _, points in groups] == [1, 0, 1]


def test_extract_speed_samples():
    observations = [
        point(77.59002, 0),
        point(77.59050, 10),
        point(77.59098, 20),
        point(77.59150, 30),
        point(77.59198, 40),
    ]

    samples = extract_speed_samples(
        observations, roads(), "driver-1", "trip-1"
    )

    assert len(samples) == 1
    assert samples[0].segment_id == "AB"
    assert samples[0].speed_kmh == 18.0


def test_match_accepts_gps_observation_objects():
    observations = [
        point(77.5902, 0),
        point(77.5908, 10),
        point(77.5912, 20),
        point(77.5918, 30),
    ]

    assert match_gps_sequence(
        observations, roads()
    ) == ["AB", "BC"]


def test_reject_ambiguous_parallel_roads():
    edges = {
        "AB": roads()["AB"],
        "XY": EdgeMeta(
            "XY", "X", "Y",
            RoadClass.RESIDENTIAL, 100,
            geometry=(
                (12.97001, 77.5900),
                (12.97001, 77.5910),
            ),
        ),
    }

    assert nearest_segment(
        (12.970005, 77.5905), edges
    ) is None


def test_time_gap_splits_same_segment():
    observations = [
        point(77.59002, 0),
        point(77.59050, 120),
        point(77.59098, 130),
    ]

    groups = group_observations_by_segment(
        observations, {"AB": roads()["AB"]}
    )

    assert [segment_id for segment_id, _ in groups] == [
        "AB", None, "AB"
    ]

    assert extract_speed_samples(
        observations,
        {"AB": roads()["AB"]},
        "driver-1",
        "trip-1",
    ) == []


def test_curved_segment_does_not_generate_speed_sample():
    curved = EdgeMeta(
        "CURVE", "A", "B",
        RoadClass.RESIDENTIAL, 200,
        geometry=(
            (12.9700, 77.5900),
            (12.9705, 77.5905),
            (12.9700, 77.5910),
        ),
    )

    observations = [
        point(77.5900, 0),
        point(77.5910, 20),
    ]

    assert speed_sample_from_observations(
        observations, curved, "driver-1", "trip-1"
    ) is None
