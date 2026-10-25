"""Tests for learned signal and turn waiting times."""

import unittest
from datetime import datetime, timedelta, timezone

from routing.delay_model import (
    DelayKind,
    DelayObservation,
    fit_delay_model,
)
from routing.time_buckets import IST, TimeBuckets

from routing import (
    CAR, EdgeMeta, LocalAStarRouter, RoadClass,
    RoadGraph, RoutingService,
)

from dataclasses import replace


BUCKETS = TimeBuckets(IST)
NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def observations(kind, wait_s, hour, count=40):
    """Create observations from different drivers and days."""
    result = []

    for i in range(count):
        day = (NOW.astimezone(IST) - timedelta(days=i % 20 + 1)).date()
        when = datetime(
            day.year, day.month, day.day,
            hour, 0, tzinfo=IST,
        )

        result.append(
            DelayObservation(
                kind=kind,
                junction_id="J1",
                driver_id=f"driver{i}",
                observed_at=when,
                wait_s=wait_s,
                inbound_segment="AB" if kind is DelayKind.TURN else None,
                outbound_segment="BC" if kind is DelayKind.TURN else None,
            )
        )

    return result


class DelayLearningTests(unittest.TestCase):

    def test_evening_signal_wait(self):
        samples = observations(DelayKind.SIGNAL, 90, 18)
        model = fit_delay_model(samples, NOW, BUCKETS)

        when = datetime(2026, 10, 26, 18, tzinfo=IST)
        self.assertGreater(model.signal_wait_s("J1", when), 65)

    def test_night_signal_wait(self):
        samples = observations(DelayKind.SIGNAL, 10, 3)
        model = fit_delay_model(samples, NOW, BUCKETS)

        when = datetime(2026, 10, 26, 3, tzinfo=IST)
        self.assertLess(model.signal_wait_s("J1", when), 20)

    def test_sparse_data_uses_default(self):
        samples = observations(DelayKind.SIGNAL, 90, 18, count=2)
        model = fit_delay_model(samples, NOW, BUCKETS)

        when = datetime(2026, 10, 26, 18, tzinfo=IST)
        self.assertEqual(model.signal_wait_s("J1", when), 30)

    def test_turn_wait_learning(self):
        samples = observations(DelayKind.TURN, 50, 18)
        model = fit_delay_model(
            samples,
            NOW,
            BUCKETS,
            turn_defaults={("AB", "BC"): 10.0},
        )

        when = datetime(2026, 10, 26, 18, tzinfo=IST)
        self.assertGreater(
            model.turn_wait_s("AB", "BC", when, 10.0),
            30,
        )

    def test_unseen_junction_uses_default(self):
        model = fit_delay_model([], NOW, BUCKETS)
        self.assertEqual(
            model.signal_wait_s("UNKNOWN", NOW),
            30.0,
        )

    def test_one_driver_cannot_dominate(self):
        honest = observations(DelayKind.SIGNAL, 10, 18, count=40)

        # One driver reports 30 pings of 600 s inside the same hour.
        spam = [
            replace(
                honest[0],
                driver_id="repeated_driver",
                observed_at=honest[0].observed_at + timedelta(minutes=i),
                wait_s=600,
            )
            for i in range(30)
        ]

        without = fit_delay_model(honest, NOW, BUCKETS)
        with_spam = fit_delay_model(honest + spam, NOW, BUCKETS)

        when = datetime(2026, 10, 26, 18, tzinfo=IST)
        shift = with_spam.signal_wait_s("J1", when) - without.signal_wait_s("J1", when)

        # 30 pings from one driver in one hour count as ONE vote, so the shift stays small.
        self.assertLess(shift, 30)

    def test_old_observations_ignored(self):
        samples = observations(
            DelayKind.SIGNAL, 90, 18
        )

        old_samples = [
            replace(
                sample,
                observed_at=sample.observed_at
                - timedelta(days=100),
            )
            for sample in samples
        ]

        model = fit_delay_model(
            old_samples, NOW, BUCKETS
        )

        when = datetime(2026, 10, 26, 18, tzinfo=IST)

        self.assertEqual(
            model.signal_wait_s("J1", when),
            30.0,
        )


class DelayRoutingIntegrationTests(unittest.TestCase):

    def test_learned_signal_changes_route(self):
        nodes = {
            "A": (12.970, 77.590),
            "B": (12.971, 77.590),
            "C": (12.970, 77.591),
            "D": (12.971, 77.591),
        }

        edges = {
            "AB": EdgeMeta(
                "AB", "A", "B", RoadClass.PRIMARY, 130,
                geometry=(nodes["A"], nodes["B"]),
            ),
            "BD": EdgeMeta(
                "BD", "B", "D", RoadClass.PRIMARY, 130,
                geometry=(nodes["B"], nodes["D"]),
            ),
            "AC": EdgeMeta(
                "AC", "A", "C", RoadClass.PRIMARY, 100,
                geometry=(nodes["A"], nodes["C"]),
                end_delay_s=30,
                end_features=frozenset({"traffic_signals"}),
            ),
            "CD": EdgeMeta(
                "CD", "C", "D", RoadClass.PRIMARY, 100,
                geometry=(nodes["C"], nodes["D"]),
            ),
        }

        svc = RoutingService(
            LocalAStarRouter(RoadGraph(nodes, list(edges.values()))),
            edges,
            profile=CAR,
            buckets=BUCKETS,
        )

        evening = datetime(2026, 10, 26, 18, tzinfo=IST)
        night = datetime(2026, 10, 26, 3, tzinfo=IST)

        # Before learning, the 30-second signal makes the right-hand
        # route preferable despite its higher turn cost.
        before = svc.route(nodes["A"], nodes["D"], depart_at=evening)
        self.assertEqual(before.segments, ["AB", "BD"])

        samples = [
            replace(obs, junction_id="C")
            for obs in (
                observations(DelayKind.SIGNAL, 90, 18)
                + observations(DelayKind.SIGNAL, 10, 3)
            )
        ]

        svc.refresh_delays(samples, NOW)

        evening_route = svc.route(
            nodes["A"], nodes["D"], depart_at=evening
        )
        night_route = svc.route(
            nodes["A"], nodes["D"], depart_at=night
        )

        self.assertEqual(evening_route.segments, ["AB", "BD"])
        self.assertEqual(night_route.segments, ["AC", "CD"])
        self.assertLess(night_route.point_delay_s, 20)

    def test_signal_uses_arrival_time_bucket(self):
        nodes = {
            "A": (12.970, 77.590),
            "B": (12.971, 77.590),
            "C": (12.972, 77.590),
        }

        edges = {
            "AB": EdgeMeta(
                "AB", "A", "B", RoadClass.PRIMARY, 100,
                geometry=(nodes["A"], nodes["B"]),
                end_delay_s=30,
                end_features=frozenset({"traffic_signals"}),
            ),
            "BC": EdgeMeta(
                "BC", "B", "C", RoadClass.PRIMARY, 100,
                geometry=(nodes["B"], nodes["C"]),
            ),
        }

        svc = RoutingService(
            LocalAStarRouter(RoadGraph(nodes, list(edges.values()))),
            edges,
            profile=CAR,
            buckets=BUCKETS,
        )

        # Learn different waits in the 17:00 and 18:00 buckets.
        samples = [
            replace(obs, junction_id="B")
            for obs in (
                observations(DelayKind.SIGNAL, 10, 17)
                + observations(DelayKind.SIGNAL, 90, 18)
            )
        ]

        svc.refresh_delays(samples, NOW)

        # Departure is before 18:00, but arrival at B is after 18:00.
        depart = datetime(2026, 10, 26, 17, 59, 55, tzinfo=IST)

        result = svc.route(
            nodes["A"], nodes["C"],
            depart_at=depart,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.segments, ["AB", "BC"])

        # The 18:00 signal wait should apply.
        self.assertGreater(result.point_delay_s, 65)

    def test_speed_sample_removes_the_learned_wait(self):
        from routing.models import SpeedSample

        nodes = {
            "A": (12.970, 77.590),
            "B": (12.971, 77.590),
            "C": (12.972, 77.590),
        }
        edges = {
            "AB": EdgeMeta(
                "AB", "A", "B", RoadClass.PRIMARY, 100,
                geometry=(nodes["A"], nodes["B"]),
                end_delay_s=30,
                end_features=frozenset({"traffic_signals"}),
            ),
            "BC": EdgeMeta(
                "BC", "B", "C", RoadClass.PRIMARY, 100,
                geometry=(nodes["B"], nodes["C"]),
            ),
        }
        svc = RoutingService(
            LocalAStarRouter(RoadGraph(nodes, list(edges.values()))),
            edges, profile=CAR, buckets=BUCKETS,
        )
        evening = datetime(2026, 10, 26, 18, tzinfo=IST)
        sample = SpeedSample("AB", "d1", "t1", 2.0, evening, CAR.vehicle)

        before = svc._without_point_delay(sample).speed_kmh

        svc.refresh_delays(
            [replace(o, junction_id="B")
             for o in observations(DelayKind.SIGNAL, 90, 18)],
            NOW,
        )
        after = svc._without_point_delay(sample).speed_kmh

        # A longer learned wait is removed, so the moving speed is higher.
        self.assertGreater(after, before)

if __name__ == "__main__":
    unittest.main()
