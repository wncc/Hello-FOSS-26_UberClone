"""Tests for extracting junction waits from GPS trips."""

import unittest
from datetime import datetime, timedelta, timezone

from routing.delay_extraction import extract_delay_observations
from routing.delay_model import DelayKind
from routing.map_matching import GPSObservation
from routing.models import EdgeMeta
from routing.road_classes import RoadClass


START = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)

A = (12.9700, 77.5900)
B = (12.9710, 77.5900)
C = (12.9720, 77.5900)
D = (12.9710, 77.5910)   # a side road leaving B

M_PER_DEG = 111_195.0


def north_of(point, metres, jitter=0.0):
    return (point[0] + metres / M_PER_DEG, point[1] + jitter / M_PER_DEG)


def make_edges(signal=True, two_way=False, side_road=False):
    features = frozenset({"traffic_signals"}) if signal else frozenset()
    edges = {
        "AB": EdgeMeta("AB", "A", "B", RoadClass.PRIMARY, 111,
                       geometry=(A, B), end_delay_s=30 if signal else 0,
                       end_features=features),
        "BC": EdgeMeta("BC", "B", "C", RoadClass.PRIMARY, 111,
                       geometry=(B, C)),
    }
    if two_way:
        edges["BA"] = EdgeMeta("BA", "B", "A", RoadClass.PRIMARY, 111,
                               geometry=(B, A))
        edges["CB"] = EdgeMeta("CB", "C", "B", RoadClass.PRIMARY, 111,
                               geometry=(C, B), end_features=features)
    if side_road:
        edges["BD"] = EdgeMeta("BD", "B", "D", RoadClass.PRIMARY, 111,
                               geometry=(B, D))
    return edges


def trip(samples):
    """samples: (lat, lng, seconds)"""
    return [GPSObservation(lat, lng, START + timedelta(seconds=s))
            for lat, lng, s in samples]


def gps_trip(wait_s=90):
    """Approach B, wait there, then continue toward C (10 s pings)."""
    samples = [(A[0] + 0.0004, A[1], 0), (B[0], B[1], 10)]
    for elapsed in range(20, wait_s + 11, 10):
        samples.append((B[0], B[1], elapsed))
    samples.append((C[0] - 0.0004, C[1], wait_s + 20))
    return trip(samples)


def drive_through():
    """A -> B -> C without stopping (pings every 4 s, ~40 km/h)."""
    return trip([
        (*north_of(B, -88), 0), (*north_of(B, -44), 4),
        (*north_of(B, 0), 8), (*north_of(B, 44), 12),
        (*north_of(B, 88), 16),
    ])


class DelayExtractionTests(unittest.TestCase):

    def test_signal_wait(self):
        result = extract_delay_observations(gps_trip(90), make_edges(), "driver1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].kind, DelayKind.SIGNAL)
        self.assertEqual(result[0].junction_id, "B")
        self.assertEqual(result[0].wait_s, 90)

    def test_turn_wait_without_signal(self):
        result = extract_delay_observations(
            gps_trip(50), make_edges(signal=False), "driver1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].kind, DelayKind.TURN)
        self.assertEqual(result[0].inbound_segment, "AB")
        self.assertEqual(result[0].outbound_segment, "BC")

    def test_mixed_timezone_timestamps_rejected_before_sorting(self):
        points = [GPSObservation(A[0], A[1], START),
                  GPSObservation(B[0], B[1], datetime(2026, 10, 20, 12))]
        with self.assertRaisesRegex(ValueError, "GPS timestamps must be timezone-aware"):
            extract_delay_observations(points, make_edges(), "driver1")

    def test_naive_timestamp_rejected_for_short_trip(self):
        points = [GPSObservation(A[0], A[1], datetime(2026, 10, 20, 12))]
        with self.assertRaisesRegex(ValueError, "GPS timestamps must be timezone-aware"):
            extract_delay_observations(points, make_edges(), "driver1")

    def test_incomplete_trip_rejected(self):
        points = gps_trip(90)[1:-1]
        self.assertEqual(
            extract_delay_observations(points, make_edges(), "driver1"), [])

    def test_large_gps_gap_rejected(self):
        points = trip([
            (A[0] + 0.0004, A[1], 0), (B[0], B[1], 10),
            (B[0], B[1], 100), (C[0] - 0.0004, C[1], 110),
        ])
        self.assertEqual(
            extract_delay_observations(points, make_edges(), "driver1"), [])

    # --- crossings without a stop -------------------------------------

    def test_signal_crossing_without_stop_is_a_zero_wait(self):
        result = extract_delay_observations(drive_through(), make_edges(), "d1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].kind, DelayKind.SIGNAL)
        self.assertEqual(result[0].wait_s, 0.0)

    def test_plain_bend_without_stop_is_ignored(self):
        # B is not a signal and offers no choice of exits: nothing to learn.
        self.assertEqual(
            extract_delay_observations(drive_through(), make_edges(signal=False), "d1"),
            [])

    def test_crossing_at_a_real_junction_without_stop_is_zero_turn_wait(self):
        edges = make_edges(signal=False, side_road=True)
        result = extract_delay_observations(drive_through(), edges, "d1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].kind, DelayKind.TURN)
        self.assertEqual((result[0].inbound_segment, result[0].outbound_segment),
                         ("AB", "BC"))
        self.assertEqual(result[0].wait_s, 0.0)

    def test_stop_is_not_also_counted_as_a_crossing(self):
        result = extract_delay_observations(gps_trip(90), make_edges(), "d1")
        self.assertEqual([o.wait_s for o in result], [90])

    # --- direction ------------------------------------------------------

    def test_two_way_roads_keep_direction(self):
        edges = make_edges(two_way=True)
        forward = extract_delay_observations(gps_trip(60), edges, "d1")
        self.assertEqual(len(forward), 1)
        self.assertEqual(forward[0].wait_s, 60)

        reverse = [GPSObservation(p.lat, p.lng, p.recorded_at)
                   for p in reversed(gps_trip(60))]
        # Re-stamp so time still runs forward while the car drives C -> B -> A.
        reverse = [GPSObservation(p.lat, p.lng, START + timedelta(seconds=10 * i))
                   for i, p in enumerate(reverse)]
        back = extract_delay_observations(reverse, make_edges(signal=False, two_way=True), "d1")
        self.assertEqual(len(back), 1)
        self.assertEqual((back[0].inbound_segment, back[0].outbound_segment),
                         ("CB", "BA"))

    # --- realistic GPS --------------------------------------------------

    def test_queue_behind_the_stop_line_with_gps_jitter(self):
        # Car waits 30 m before the junction, pings every 4 s, +-3 m jitter.
        samples = [(*north_of(B, -90), 0), (*north_of(B, -60), 4)]
        jitter = [3, -2, 1, -3, 2, 0, -1, 3, -2, 1, 2, -3, 1, 0, -2]
        for i, j in enumerate(jitter):
            samples.append((*north_of(B, -30 + j % 3, jitter=j), 8 + 4 * i))
        t = 8 + 4 * len(jitter)
        samples += [(*north_of(B, 20), t), (*north_of(B, 60), t + 4)]
        result = extract_delay_observations(trip(samples), make_edges(), "d1")
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].wait_s, 4 * (len(jitter) - 1), delta=4)

    def test_queue_before_a_fast_crossing_is_not_a_zero_wait(self):
        # Waits 40 m back for 60 s, then crosses in two quick steps.
        samples = [(*north_of(B, -80), 0)]
        samples += [(*north_of(B, -40), 4 + 4 * i) for i in range(16)]
        samples += [(*north_of(B, 5), 72), (*north_of(B, 50), 76)]
        result = extract_delay_observations(trip(samples), make_edges(), "d1")
        self.assertEqual([o.wait_s for o in result], [60])

    def test_wait_longer_than_limit_is_dropped(self):
        result = extract_delay_observations(gps_trip(700), make_edges(), "d1")
        self.assertEqual(result, [])

    def test_two_minute_wait_is_kept(self):
        result = extract_delay_observations(gps_trip(240), make_edges(), "d1")
        self.assertEqual([o.wait_s for o in result], [240])

    # --- feeding the model ---------------------------------------------

    def _trips(self, wait_s, drivers=5, days=3):
        out = []
        for day in range(days):
            for driver in range(drivers):
                shifted = [
                    GPSObservation(p.lat, p.lng,
                                   p.recorded_at + timedelta(days=day, minutes=driver))
                    for p in gps_trip(wait_s)
                ]
                out.append((f"driver{driver}", shifted))
        return out

    def test_gps_waits_can_fit_delay_model(self):
        from routing.delay_model import fit_delay_model
        from routing.time_buckets import IST, TimeBuckets

        edges = make_edges()
        observations = []
        for driver, points in self._trips(90):
            observations.extend(extract_delay_observations(points, edges, driver))
        self.assertEqual(len(observations), 15)

        model = fit_delay_model(observations, START + timedelta(days=3), TimeBuckets(IST))
        learned = model.signal_wait_s("B", START + timedelta(days=2, minutes=5))
        self.assertGreater(learned, 65)
        self.assertLess(learned, 90)

    def test_drivers_who_do_not_stop_pull_the_average_down(self):
        from routing.delay_model import fit_delay_model
        from routing.time_buckets import IST, TimeBuckets

        edges = make_edges()
        observations = []
        for day in range(3):
            for driver in range(6):
                when = timedelta(days=day, minutes=driver)
                stop = driver % 2 == 0           # half stop for 60 s, half drive through
                points = gps_trip(60) if stop else [
                    GPSObservation(p.lat, p.lng, p.recorded_at)
                    for p in drive_through()]
                points = [GPSObservation(p.lat, p.lng, p.recorded_at + when)
                          for p in points]
                observations.extend(
                    extract_delay_observations(points, edges, f"driver{driver}"))

        model = fit_delay_model(observations, START + timedelta(days=3),
                                TimeBuckets(IST), signal_default_s=30.0)
        learned = model.signal_wait_s("B", START + timedelta(days=2, minutes=5))
        # Expected wait is about 30 s (half stop 60 s, half 0 s), not 60 s.
        self.assertGreater(learned, 20)
        self.assertLess(learned, 40)


if __name__ == "__main__":
    unittest.main()
