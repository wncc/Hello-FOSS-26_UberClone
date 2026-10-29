"""Starting congestion table and speed-model prior (issue 001, step 2)."""
import math
import unittest
from datetime import datetime

from routing import (
    CAR, IST, CongestionPrior, EdgeMeta, LocalAStarRouter,
    RoadClass, RoadGraph, RoutingService, SpeedSample, TimeBuckets, fit_speed_model, EtaCalibrator
)
from routing.models import free_flow_speed_kmh
from routing.time_buckets import HOURS, SATURDAY, SUNDAY, WEEKDAY

BUCKETS = TimeBuckets(IST)


def _edge(seg_id: str, a: str, b: str, rc: RoadClass, dist_m: float = 1000.0) -> EdgeMeta:
    return EdgeMeta(
        segment_id=seg_id, from_node=a, to_node=b, road_class=rc, distance_m=dist_m,
        speed_kmh=free_flow_speed_kmh(rc, None, CAR),
    )


class CongestionPriorTests(unittest.TestCase):
    def test_weekday_table_values_for_main_and_minor_roads(self):
        prior = CongestionPrior.default()
        expected = [
            (0, 1.0, 1.0), (5, 1.0, 1.0),
            (6, 1.15, 1.1), (7, 1.15, 1.1),
            (8, 1.8, 1.4), (9, 1.8, 1.4), (10, 1.8, 1.4),
            (11, 1.4, 1.2), (16, 1.4, 1.2),
            (17, 2.0, 1.5), (20, 2.0, 1.5),
            (21, 1.2, 1.1), (23, 1.2, 1.1),
        ]
        for hour, main_s, minor_s in expected:
            b = WEEKDAY * HOURS + hour
            self.assertAlmostEqual(prior.slowdown(RoadClass.PRIMARY, b), main_s)
            self.assertAlmostEqual(prior.slowdown(RoadClass.TERTIARY, b), main_s)
            self.assertAlmostEqual(prior.slowdown(RoadClass.RESIDENTIAL, b), minor_s)
            self.assertAlmostEqual(prior.slowdown(RoadClass.UNCLASSIFIED, b), minor_s)

    def test_weekend_scales_excess_over_one(self):
        prior = CongestionPrior.default()
        # 17:00-20:00 weekday: main = 2.0 (excess 1.0), minor = 1.5 (excess 0.5)
        sat_18 = SATURDAY * HOURS + 18
        sun_18 = SUNDAY * HOURS + 18
        self.assertAlmostEqual(prior.slowdown(RoadClass.PRIMARY, sat_18), 1.0 + 0.8 * 1.0)
        self.assertAlmostEqual(prior.slowdown(RoadClass.PRIMARY, sun_18), 1.0 + 0.5 * 1.0)
        self.assertAlmostEqual(prior.slowdown(RoadClass.RESIDENTIAL, sat_18), 1.0 + 0.8 * 0.5)
        self.assertAlmostEqual(prior.slowdown(RoadClass.RESIDENTIAL, sun_18), 1.0 + 0.5 * 0.5)

    def test_speed_model_starts_from_ln_slowdown_without_telemetry(self):
        edges = {
            "main": _edge("main", "A", "B", RoadClass.PRIMARY),
            "minor": _edge("minor", "B", "C", RoadClass.RESIDENTIAL),
        }
        now = datetime(2026, 3, 2, 12, 0, tzinfo=IST)  # Monday
        model = fit_speed_model(edges, [], now, BUCKETS)
        b_03 = WEEKDAY * HOURS + 3
        b_09 = WEEKDAY * HOURS + 9
        self.assertAlmostEqual(model.traffic_log(edges["main"], b_03), 0.0)
        self.assertAlmostEqual(model.traffic_log(edges["main"], b_09), math.log(1.8))
        self.assertAlmostEqual(model.traffic_log(edges["minor"], b_09), math.log(1.4))

    def test_eta_at_weekday_09_is_longer_than_at_03_before_any_telemetry(self):
        # Acceptance criterion 1 from Issue #1.
        nodes = {"A": (19.00, 72.80), "B": (19.01, 72.80), "C": (19.02, 72.80)}
        e1 = EdgeMeta("e1", "A", "B", RoadClass.PRIMARY, 1000.0,
                      speed_kmh=free_flow_speed_kmh(RoadClass.PRIMARY, None, CAR),
                      geometry=(nodes["A"], nodes["B"]))
        e2 = EdgeMeta("e2", "B", "C", RoadClass.RESIDENTIAL, 500.0,
                      speed_kmh=free_flow_speed_kmh(RoadClass.RESIDENTIAL, None, CAR),
                      geometry=(nodes["B"], nodes["C"]))
        edges = {"e1": e1, "e2": e2}
        svc = RoutingService(LocalAStarRouter(RoadGraph(nodes, [e1, e2])), edges, buckets=BUCKETS)

        t_03 = datetime(2026, 3, 2, 3, 0, tzinfo=IST)   # Monday 03:00 IST
        t_09 = datetime(2026, 3, 2, 9, 0, tzinfo=IST)   # Monday 09:00 IST
        r_03 = svc.route(nodes["A"], nodes["C"], now=t_03, depart_at=t_03)
        r_09 = svc.route(nodes["A"], nodes["C"], now=t_09, depart_at=t_09)
        assert r_03 is not None and r_09 is not None
        self.assertGreater(r_09.eta_s, r_03.eta_s)

    def test_learned_data_gradually_replaces_prior(self):
        e = _edge("main", "A", "B", RoadClass.PRIMARY)
        edges = {"main": e}
        t_09 = datetime(2026, 3, 2, 9, 0, tzinfo=IST)   # Monday 09:00 (prior slowdown = 1.8)
        t_03 = datetime(2026, 3, 2, 3, 0, tzinfo=IST)   # Monday 03:00 (quiet anchor = 1.0)
        # Feed many observations showing 09:00 actually moves at free-flow speed (no slowdown).
        samples = [
            SpeedSample("main", f"d{i}", f"t{i}", e.speed_kmh, t_09)
            for i in range(60)
        ] + [
            SpeedSample("main", f"q{i}", f"tq{i}", e.speed_kmh, t_03)
            for i in range(30)
        ]
        model = fit_speed_model(edges, samples, t_09, BUCKETS)
        # With 60 recent samples (weight 60 vs prior k=20), slowdown shrinks from 1.8 toward 1.0:
        self.assertLess(model.slowdown(e, t_09), 1.2)
        self.assertGreater(model.slowdown(e, t_09), 1.0)


class EtaCalibratorTests(unittest.TestCase):
    def test_uncalibrated_multiplier_is_one(self):
        cal = EtaCalibrator(BUCKETS, k=20.0)
        t_09 = datetime(2026, 3, 2, 9, 0, tzinfo=IST)
        self.assertAlmostEqual(cal.multiplier(t_09), 1.0)
        self.assertAlmostEqual(cal.calibrate(300.0, t_09), 300.0)

    def test_two_stage_shrinkage_toward_global_and_bucket_mean(self):
        cal = EtaCalibrator(BUCKETS, k=20.0)
        t_09 = datetime(2026, 3, 2, 9, 0, tzinfo=IST)   # bucket 9
        t_03 = datetime(2026, 3, 2, 3, 0, tzinfo=IST)   # bucket 3

        # 20 trips at 09:00 took 1.5x longer than predicted:
        for _ in range(20):
            cal.record(predicted_s=100.0, actual_s=150.0, departed_at=t_09)

        # Global log error: N=20, k=20 -> g = 20 * ln(1.5) / 40 = 0.5 * ln(1.5)
        expected_g = 0.5 * math.log(1.5)
        self.assertAlmostEqual(cal.global_log_error(), expected_g)

        # Unobserved bucket (03:00, n_b=0) shrinks 100% to global error g:
        self.assertAlmostEqual(cal.log_multiplier(t_03), expected_g)

        # Observed bucket (09:00, n_b=20) blends 20*ln(1.5) + 20*g over 40 = 0.75 * ln(1.5):
        self.assertAlmostEqual(cal.log_multiplier(t_09), 0.75 * math.log(1.5))
        self.assertGreater(cal.multiplier(t_09), cal.multiplier(t_03))

    def test_outliers_are_clipped_to_three_times(self):
        cal = EtaCalibrator(BUCKETS, k=20.0)
        t_09 = datetime(2026, 3, 2, 9, 0, tzinfo=IST)
        # 100x outlier should be clipped to 3x (+ln 3)
        cal.record(predicted_s=100.0, actual_s=10000.0, departed_at=t_09)
        self.assertAlmostEqual(cal.global_log_error(), math.log(3.0) / 21.0)

    def test_median_ape_is_tracked_per_bucket(self):
        cal = EtaCalibrator(BUCKETS)
        t_09 = datetime(2026, 3, 2, 9, 0, tzinfo=IST)
        for _ in range(40):
            cal.record(100.0, 150.0, t_09)
        b9, b3 = WEEKDAY * HOURS + 9, WEEKDAY * HOURS + 3
        raw, fixed = cal.median_ape(b9, calibrated=False), cal.median_ape(b9)
        assert raw is not None and fixed is not None
        self.assertAlmostEqual(raw, 1 / 3)
        self.assertLess(fixed, raw)
        self.assertIsNone(cal.median_ape(b3))          # no trips in that bucket
        self.assertIsNone(EtaCalibrator(BUCKETS).median_ape())

    def test_median_ape_before_and_after_calibration(self):
        cal = EtaCalibrator(BUCKETS, k=20.0)
        t_09 = datetime(2026, 3, 2, 9, 0, tzinfo=IST)
        for _ in range(10):
            cal.record(predicted_s=100.0, actual_s=150.0, departed_at=t_09)
        raw, fixed = cal.median_ape(calibrated=False), cal.median_ape(calibrated=True)
        assert raw is not None and fixed is not None
        self.assertGreater(raw, fixed)

class RouteEtaCalibrationTests(unittest.TestCase):
    def setUp(self):
        nodes = {"A": (19.00, 72.80), "B": (19.01, 72.80), "C": (19.02, 72.80)}
        e1 = EdgeMeta("e1", "A", "B", RoadClass.PRIMARY, 1000.0, speed_kmh=40.0, geometry=(nodes["A"], nodes["B"]))
        e2 = EdgeMeta("e2", "B", "C", RoadClass.PRIMARY, 1000.0, speed_kmh=40.0, geometry=(nodes["B"], nodes["C"]))
        self.nodes = nodes
        self.svc = RoutingService(LocalAStarRouter(RoadGraph(nodes, [e1, e2])), {"e1": e1, "e2": e2},
                                  buckets=BUCKETS)
        self.t_09 = datetime(2026, 3, 2, 9, 0, tzinfo=IST)

    def _route(self) -> tuple[float, float]:
        """(calibrated eta_s, uncalibrated eta_s) for A -> C at Monday 09:00."""
        res = self.svc.route(self.nodes["A"], self.nodes["C"], now=self.t_09, depart_at=self.t_09)
        assert res is not None and res.uncalibrated_eta_s is not None
        return res.eta_s, res.uncalibrated_eta_s

    def test_untrained_calibrator_changes_nothing(self):
        eta, raw = self._route()
        self.assertAlmostEqual(eta, raw)

    def test_recording_raw_eta_corrects_eta_without_moving_the_raw_one(self):
        _, raw = self._route()
        for _ in range(40):
            self.svc.record_trip_eta(raw, raw * 1.4, self.t_09)
        eta, raw_after = self._route()
        self.assertAlmostEqual(raw_after, raw)    # learning never changes the raw ETA
        self.assertGreater(eta, raw)
        self.assertLess(eta, raw * 1.4)


class CustomGroupPriorTests(unittest.TestCase):
    def test_prior_applies_when_group_of_is_not_the_default_function(self):
        e = EdgeMeta("main", "A", "B", RoadClass.PRIMARY, 1000.0, speed_kmh=40.0)
        edges = {"main": e}
        t_09 = datetime(2026, 3, 2, 9, 0, tzinfo=IST)
        t_03 = datetime(2026, 3, 2, 3, 0, tzinfo=IST)
        samples = [SpeedSample("main", f"d{i}", f"t{i}", 40.0, t_09) for i in range(30)] + [
            SpeedSample("main", f"q{i}", f"tq{i}", 40.0, t_03) for i in range(30)]   # quiet-hour anchor
        same_groups = lambda edge: edge.road_class.value
        a = fit_speed_model(edges, samples, t_09, BUCKETS)
        b = fit_speed_model(edges, samples, t_09, BUCKETS, group_of=same_groups)
        self.assertAlmostEqual(a.slowdown(e, t_09), b.slowdown(e, t_09))

        
if __name__ == "__main__":
    unittest.main()