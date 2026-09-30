"""Speed model: separating road condition from time-of-week traffic; ETA; time-scoped avoidance.

Synthetic ground truth: primary roads slow down 2x at weekday 09:00 and 18:00,
1.3x at 14:00, 1.2x at weekend peaks; residential roads have no traffic.
PBAD (primary) and RBAD (residential) are in poor condition: always 0.6x / 0.5x.
"""
import random
import unittest
from datetime import datetime, timedelta, timezone

from routing import (
    IST, EdgeMeta, LocalAStarRouter, RoadClass, RoadGraph, RoutingService, SegmentExposure,
    SegmentKind, SpeedSample, TimeBuckets, fit_speed_model, route_eta_s,
)
from routing.rule_engine import CompiledModel
from routing.telemetry import aggregate, derive_rules

NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)  # Friday
BUCKETS = TimeBuckets(IST)
HOURS = (2, 9, 14, 18, 23)
CONDITION = {"PBAD": 0.6, "RBAD": 0.5}


def _edges():
    specs = [(f"P{i}", RoadClass.PRIMARY) for i in range(1, 6)] + [("PBAD", RoadClass.PRIMARY)]
    specs += [(f"R{i}", RoadClass.RESIDENTIAL) for i in range(1, 5)] + [("RBAD", RoadClass.RESIDENTIAL)]
    nodes, edges = {}, []
    for i, (seg, rc) in enumerate(specs):
        a, b = (12.9 + i * 0.01, 77.5), (12.9 + i * 0.01, 77.51)
        nodes[f"{seg}a"], nodes[f"{seg}b"] = a, b
        edges.append(EdgeMeta(seg, f"{seg}a", f"{seg}b", rc, 1000.0, geometry=(a, b)))
    return nodes, {e.segment_id: e for e in edges}


NODES, EDGES = _edges()


def true_traffic(rc: RoadClass, local: datetime) -> float:
    if rc is not RoadClass.PRIMARY:
        return 1.0
    weekend = local.weekday() >= 5
    if local.hour in (9, 18):
        return 1.2 if weekend else 2.0
    if local.hour == 14 and not weekend:
        return 1.3
    return 1.0


def synth_samples(segments=None, hours=HOURS, days=28, per_hour=3, seed=7):
    rng = random.Random(seed)
    out = []
    for seg, edge in EDGES.items():
        if segments and seg not in segments:
            continue
        for d in range(1, days + 1):
            day = (NOW.astimezone(IST) - timedelta(days=d)).date()
            for h in hours:
                local = datetime(day.year, day.month, day.day, h, 15, tzinfo=IST)
                for k in range(per_hour):
                    speed = edge.speed_kmh * CONDITION.get(seg, 1.0) / true_traffic(edge.road_class, local)
                    out.append(SpeedSample(seg, f"drv{(d * 3 + k) % 12}", f"t{seg}{d}{h}{k}",
                                           speed * rng.uniform(0.95, 1.05), local.astimezone(timezone.utc)))
    return out


def at_local(weekday_offset_days: int, hour: int) -> datetime:
    """A local time on a weekday in the past (NOW is Friday; offset 3 = Tuesday)."""
    day = (NOW.astimezone(IST) - timedelta(days=weekday_offset_days)).date()
    return datetime(day.year, day.month, day.day, hour, 10, tzinfo=IST)


class BucketTests(unittest.TestCase):
    def test_buckets(self):
        self.assertEqual(BUCKETS.of(datetime(2026, 9, 28, 9, 30, tzinfo=IST)), 9)        # Monday
        self.assertEqual(BUCKETS.of(datetime(2026, 9, 26, 9, 30, tzinfo=IST)), 24 + 9)   # Saturday
        self.assertEqual(BUCKETS.of(datetime(2026, 9, 27, 4, 0, tzinfo=timezone.utc)), 48 + 9)  # Sun 09:30 IST
        with self.assertRaises(ValueError):
            BUCKETS.of(datetime(2026, 9, 28, 9))


class SpeedModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = fit_speed_model(EDGES, synth_samples(), NOW, BUCKETS)

    def test_condition_is_separated_from_traffic(self):
        m = self.model
        self.assertAlmostEqual(m.condition_factor("PBAD"), 0.6, delta=0.06)
        self.assertAlmostEqual(m.condition_factor("RBAD"), 0.5, delta=0.06)
        self.assertAlmostEqual(m.condition_factor("P1"), 1.0, delta=0.06)

    def test_traffic_profile_is_learned(self):
        m, p1 = self.model, EDGES["P1"]
        self.assertAlmostEqual(m.slowdown(p1, at_local(3, 9)), 2.0, delta=0.2)
        self.assertAlmostEqual(m.slowdown(p1, at_local(3, 14)), 1.3, delta=0.15)
        self.assertAlmostEqual(m.slowdown(p1, at_local(3, 2)), 1.0, delta=0.1)
        self.assertAlmostEqual(m.slowdown(EDGES["R1"], at_local(3, 9)), 1.0, delta=0.1)

    def test_diagnosis(self):
        kinds = {seg: self.model.diagnose(EDGES[seg]).kind for seg in ("P1", "PBAD", "R1", "RBAD")}
        self.assertEqual(kinds, {"P1": SegmentKind.TRAFFIC, "PBAD": SegmentKind.BOTH,
                                 "R1": SegmentKind.NORMAL, "RBAD": SegmentKind.CONDITION})

    def test_speed_estimate_combines_both(self):
        self.assertAlmostEqual(self.model.speed_kmh(EDGES["PBAD"], at_local(3, 9)), 30 * 0.6 / 2.0, delta=1.5)

    def test_one_driver_is_one_vote_per_hour(self):
        start = at_local(1, 10)
        spam = [SpeedSample("P1", "d1", f"t{i}", 20.0, start + timedelta(minutes=i)) for i in range(50)]
        many = [SpeedSample("P1", f"d{i}", f"t{i}", 20.0, start + timedelta(minutes=i)) for i in range(50)]
        self.assertLess(fit_speed_model(EDGES, spam, NOW, BUCKETS).weight["P1"], 1.01)
        self.assertGreater(fit_speed_model(EDGES, many, NOW, BUCKETS).weight["P1"], 45)  # decayed


class ConditionRuleTests(unittest.TestCase):
    def test_rush_hour_skew_no_longer_looks_like_bad_road(self):
        # Ride demand clusters at peaks: P1 is only ever observed at 09:00 and 18:00.
        samples = synth_samples(segments=set(EDGES) - {"P1"}) + synth_samples(segments={"P1"}, hours=(9, 18))
        model = fit_speed_model(EDGES, samples, NOW, BUCKETS)

        naive, _ = derive_rules(EDGES, aggregate(samples, [], NOW), NOW)
        detrended, _ = derive_rules(EDGES, aggregate(samples, [], NOW, traffic=model), NOW, traffic=model)

        self.assertIn("tele.speed.P1", {r.rule_id for r in naive})
        ids = {r.rule_id: r for r in detrended}
        self.assertNotIn("tele.speed.P1", ids)
        self.assertIn("tele.speed.PBAD", ids)
        self.assertAlmostEqual(ids["tele.speed.PBAD"].value, 30 * 0.6, delta=2)


class TimeScopedAvoidanceTests(unittest.TestCase):
    def _service(self):
        return RoutingService(LocalAStarRouter(RoadGraph(NODES, list(EDGES.values()))), EDGES,
                              buckets=BUCKETS)

    def test_peak_only_avoidance_applies_only_at_peak(self):
        svc = self._service()
        exposures = [SegmentExposure("P1", f"d{i % 8}", f"t{i}", i % 4 == 0,
                                     at_local(3 + 7 * (i % 3), 9).astimezone(timezone.utc)) for i in range(40)]
        rules = svc.refresh_telemetry(synth_samples(), exposures, NOW)
        ids = {r.rule_id: r for r in rules}
        self.assertNotIn("tele.dev.P1", ids)
        peak = ids["tele.dev.peak.P1"]
        self.assertIn(9, peak.active_buckets)
        self.assertNotIn(2, peak.active_buckets)

        def priority(local_hour):
            model = svc.model_for_request(NOW, depart_at=at_local(-4, local_hour))  # next Tuesday
            return CompiledModel(model).evaluate(EDGES["P1"]).priority
        self.assertAlmostEqual(priority(9), peak.value)
        self.assertAlmostEqual(priority(2), 1.0)

    def test_request_gets_traffic_for_departure_time(self):
        svc = self._service()
        svc.refresh_telemetry(synth_samples(), [], NOW)
        speed = lambda h: CompiledModel(svc.model_for_request(NOW, at_local(-4, h))).evaluate(EDGES["P1"]).speed_kmh
        self.assertAlmostEqual(speed(9), 15, delta=1.5)
        self.assertAlmostEqual(speed(2), 30, delta=0.5)

    def test_map_error_flag(self):
        svc = self._service()
        exposures = [SegmentExposure("R1", f"d{i % 15}", f"t{i}", i % 20 == 0,
                                     (NOW - timedelta(days=i % 4 + 1)).replace(hour=20)) for i in range(200)]
        svc.refresh_telemetry([], exposures, NOW)
        self.assertTrue(svc.health["R1"].suspected_map_error)


class EtaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.road = [EdgeMeta(f"s{i}", str(i), str(i + 1), RoadClass.PRIMARY, 1000.0) for i in range(30)]
        samples = [SpeedSample(e.segment_id, x.driver_id, x.trip_id, x.speed_kmh, x.observed_at)
                   for x in synth_samples(segments={"P1"}) for e in cls.road]
        cls.fit = fit_speed_model({e.segment_id: e for e in cls.road}, samples, NOW, BUCKETS)

    def test_eta_depends_on_departure(self):
        night = route_eta_s(self.road[:10], at_local(-4, 3), self.fit.speed_kmh)
        peak = route_eta_s(self.road[:10], at_local(-4, 9), self.fit.speed_kmh)
        self.assertAlmostEqual(night, 1200, delta=60)          # 10 km at 30 km/h
        self.assertAlmostEqual(peak / night, 1.9, delta=0.2)

    def test_eta_crosses_into_rush_hour(self):
        eta = route_eta_s(self.road, at_local(-4, 8).replace(minute=40), self.fit.speed_kmh)
        self.assertGreater(eta, 3600 * 1.2)   # slower than 30 km at free flow (1 h)
        self.assertLess(eta, 3600 * 1.9)      # faster than if the whole trip were at peak


if __name__ == "__main__":
    unittest.main()
