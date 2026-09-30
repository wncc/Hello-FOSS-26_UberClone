import random
import unittest
from datetime import datetime, timedelta, timezone

from routing import (
    EdgeMeta, LocalAStarRouter, Op, RoadClass, RoadClassIs, RoadGraph, RoutingService,
    SegmentExposure, SegmentIs, Source, SpeedSample, Statement, Target, baseline_model,
    detect_exposures, merge_models, to_graphhopper,
)
from routing.graph import haversine_m
from routing.rule_engine import CompiledModel, RuleValidationError, validate

NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)

# Every road has the same speed; only priority prefers the main road.
#   A ── primary (longer) ── B ── primary ── C
#   A ── residential (shorter) ── R ── residential ── C
NODES = {
    "A": (12.9700, 77.5900),
    "B": (12.9725, 77.5950),
    "C": (12.9700, 77.6000),
    "R": (12.9700, 77.5950),
}


def _edge(seg, a, b, rc):
    return EdgeMeta(seg, a, b, rc, haversine_m(NODES[a], NODES[b]), geometry=(NODES[a], NODES[b]))


EDGES = [
    _edge("AB", "A", "B", RoadClass.PRIMARY),
    _edge("BC", "B", "C", RoadClass.PRIMARY),
    _edge("AR", "A", "R", RoadClass.RESIDENTIAL),
    _edge("RC", "R", "C", RoadClass.RESIDENTIAL),
]
EDGE_MAP = {e.segment_id: e for e in EDGES}


def service():
    return RoutingService(LocalAStarRouter(RoadGraph(NODES, EDGES)), EDGE_MAP)


def speed_samples(seg, speed, drivers, per_driver, days):
    return [SpeedSample(seg, f"d{d}", f"t{d}-{i}", speed, NOW - timedelta(days=i % days, hours=1))
            for d in range(drivers) for i in range(per_driver)]


def exposures(seg, total, deviated, drivers, days):
    return [SegmentExposure(seg, f"d{i % drivers}", f"t{i}", i >= deviated, NOW - timedelta(days=i % days, hours=1))
            for i in range(total)]


class BaselineTests(unittest.TestCase):
    def test_pure_time_would_pick_residential(self):
        flat = baseline_model()
        flat.priority.clear()
        r = LocalAStarRouter(RoadGraph(NODES, EDGES)).route(NODES["A"], NODES["C"], flat)
        self.assertEqual(r.segments, ["AR", "RC"])

    def test_baseline_prefers_main_road(self):
        r = service().route(NODES["A"], NODES["C"], NOW)
        self.assertEqual(r.segments, ["AB", "BC"])
        self.assertAlmostEqual(r.explanation[0].priority, 1.0)


class TelemetryTests(unittest.TestCase):
    def test_soft_slowdown_keeps_hierarchy(self):
        svc = service()
        rules = svc.refresh_telemetry(speed_samples("AB", 10, drivers=10, per_driver=3, days=2), [], NOW)
        self.assertEqual([r.rule_id for r in rules], ["tele.speed.AB"])
        self.assertGreaterEqual(rules[0].value, 15)  # soft cap: at most half of 30 km/h
        self.assertEqual(svc.route(NODES["A"], NODES["C"], NOW).segments, ["AB", "BC"])

    def test_soft_deviation_is_bounded(self):
        svc = service()
        rules = svc.refresh_telemetry([], exposures("AB", total=25, deviated=20, drivers=6, days=1), NOW)
        self.assertEqual(rules[0].value, 0.7)
        self.assertEqual(svc.route(NODES["A"], NODES["C"], NOW).segments, ["AB", "BC"])

    def test_hard_deviation_kills_edge(self):
        svc = service()
        rules = svc.refresh_telemetry([], exposures("AB", total=200, deviated=190, drivers=15, days=4), NOW)
        self.assertEqual(rules[0].value, 0.01)
        self.assertEqual(svc.route(NODES["A"], NODES["C"], NOW).segments, ["AR", "RC"])

    def test_single_driver_is_not_consensus(self):
        rules = service().refresh_telemetry(speed_samples("AB", 5, drivers=1, per_driver=300, days=5), [], NOW)
        self.assertEqual(rules, [])

    def test_hysteresis(self):
        svc = service()
        svc.refresh_telemetry(speed_samples("AB", 10, drivers=10, per_driver=3, days=2), [], NOW)
        # Moderate recovery: above the enter threshold (0.70) but below exit (0.80) -> rule stays.
        recovering = speed_samples("AB", 20, drivers=10, per_driver=8, days=3)
        self.assertEqual(len(svc.refresh_telemetry(recovering, [], NOW)), 1)
        self.assertEqual(len(service().refresh_telemetry(recovering, [], NOW)), 0)

    def test_old_data_decays(self):
        old = [SpeedSample(s.segment_id, s.driver_id, s.trip_id, s.speed_kmh, s.observed_at - timedelta(days=90))
               for s in speed_samples("AB", 10, drivers=10, per_driver=5, days=2)]
        self.assertEqual(service().refresh_telemetry(old, [], NOW), [])

    def test_residential_never_boosted(self):
        svc = service()
        svc.refresh_telemetry(speed_samples("AR", 29, 10, 5, 3), exposures("AR", 50, 0, 10, 3), NOW)
        ev = CompiledModel(svc.model_for_request(NOW)).evaluate(EDGE_MAP["AR"])
        self.assertLessEqual(ev.priority, 0.5)
        self.assertLessEqual(ev.speed_kmh, 30)


class RuleEngineTests(unittest.TestCase):
    def _stmt(self, target, seg, op, value, source=Source.TELEMETRY_DEVIATION, rid=None, **kw):
        return Statement(target, SegmentIs(seg), op, value, source, rid or f"r.{seg}.{value}", **kw)

    def test_overlays_cannot_boost(self):
        with self.assertRaises(RuleValidationError):
            validate(self._stmt(Target.PRIORITY, "AB", Op.MULTIPLY_BY, 1.5))
        with self.assertRaises(RuleValidationError):
            validate(self._stmt(Target.PRIORITY, "AB", Op.MULTIPLY_BY, 0.0))  # only ops may block

    def test_merge_is_order_independent(self):
        overlays = [self._stmt(Target.PRIORITY, "AB", Op.MULTIPLY_BY, 0.5, rid="x"),
                    self._stmt(Target.SPEED, "AB", Op.LIMIT_TO, 15, Source.TELEMETRY_SPEED, rid="y"),
                    self._stmt(Target.PRIORITY, "AB", Op.MULTIPLY_BY, 0.8, Source.OPS, rid="z")]
        results = set()
        for _ in range(5):
            random.shuffle(overlays)
            ev = CompiledModel(merge_models(baseline_model(), [overlays], NOW)).evaluate(EDGE_MAP["AB"])
            results.add((ev.speed_kmh, round(ev.priority, 9)))
        self.assertEqual(results, {(15.0, 0.4)})

    def test_duplicates_keep_strictest(self):
        a = self._stmt(Target.PRIORITY, "AB", Op.MULTIPLY_BY, 0.5, rid="a")
        b = self._stmt(Target.PRIORITY, "AB", Op.MULTIPLY_BY, 0.3, rid="b")
        ev = CompiledModel(merge_models(baseline_model(), [[a], [b]], NOW)).evaluate(EDGE_MAP["AB"])
        self.assertAlmostEqual(ev.priority, 0.3)

    def test_expired_rules_dropped(self):
        s = self._stmt(Target.PRIORITY, "AB", Op.MULTIPLY_BY, 0.01, expires_at=NOW - timedelta(seconds=1))
        self.assertEqual(len(merge_models(baseline_model(), [[s]], NOW).priority), len(baseline_model().priority))

    def test_ops_closure_blocks(self):
        svc = service()
        svc.set_ops_rules([self._stmt(Target.PRIORITY, "AB", Op.MULTIPLY_BY, 0, Source.OPS, rid="closure")])
        self.assertEqual(svc.route(NODES["A"], NODES["C"], NOW).segments, ["AR", "RC"])


class IntegrationFormatTests(unittest.TestCase):
    def test_graphhopper_serialization(self):
        overlays = [
            Statement(Target.SPEED, SegmentIs("15933"), Op.LIMIT_TO, 15, Source.TELEMETRY_SPEED, "s"),
            Statement(Target.PRIORITY, SegmentIs("8442"), Op.MULTIPLY_BY, 0.01, Source.TELEMETRY_DEVIATION, "p"),
        ]
        gh = to_graphhopper(merge_models(baseline_model(), [overlays], NOW), {}, segment_mode="expression")
        self.assertEqual(gh["speed"], [{"if": "true", "limit_to": 30.0},
                                       {"if": "true", "limit_to": "max_speed"},
                                       {"if": "segment_id == 15933", "limit_to": 15.0}])
        self.assertIn({"if": "road_class == RESIDENTIAL", "multiply_by": 0.5}, gh["priority"])
        self.assertEqual(gh["priority"][-1], {"if": "segment_id == 8442", "multiply_by": 0.01})

    def test_graphhopper_area_mode(self):
        s = Statement(Target.PRIORITY, SegmentIs("AB", RoadClass.PRIMARY), Op.MULTIPLY_BY, 0.01,
                      Source.TELEMETRY_DEVIATION, "p")
        gh = to_graphhopper(merge_models(baseline_model(), [[s]], NOW), EDGE_MAP, include_baseline=False)
        self.assertEqual(gh["priority"], [{"if": "in_seg_AB && road_class == PRIMARY", "multiply_by": 0.01}])
        ring = gh["areas"]["features"][0]["geometry"]["coordinates"][0]
        self.assertEqual(ring[0], ring[-1])

    def test_detect_exposures(self):
        ev = detect_exposures(["AB", "BC"], ["AR", "RC"], "t1", "d1", NOW)
        self.assertEqual([(e.segment_id, e.followed) for e in ev], [("AB", False)])
        ev = detect_exposures(["AB", "BC"], ["AB", "BC"], "t1", "d1", NOW)
        self.assertTrue(all(e.followed for e in ev))
        self.assertEqual(detect_exposures(["AB", "BC"], ["AB"], "t1", "d1", NOW)[-1].followed, True)


class DeployConfigTests(unittest.TestCase):
    def test_server_baseline_matches_code(self):
        import json
        from pathlib import Path
        file = Path(__file__).parent.parent / "deploy" / "graphhopper" / "car_hierarchy.json"

        def norm(statements):
            out = []
            for st in statements:
                (op, value), = ((k, v) for k, v in st.items() if k != "if")
                try:
                    value = float(value)
                except ValueError:
                    pass
                out.append((st["if"], op, value))
            return out

        server = json.loads(file.read_text())
        code = to_graphhopper(baseline_model(), {}, include_baseline=True)
        for key in ("speed", "priority"):
            self.assertEqual(norm(server[key]), norm(code[key]), key)


if __name__ == "__main__":
    unittest.main()
