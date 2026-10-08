"""Turns (left-hand traffic), point delays, speed breakers, and per-vehicle routing."""
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from routing import (
    AUTO, BIKE, CAR, EdgeMeta, LocalAStarRouter, MultiVehicleRouter, RoadAccess, RoadClass, RoadGraph,
    RoutingService, SpeedSample, Turn, TurnRestrictions, VehicleType, baseline_model,
    classify_turn, expected_speed_kmh, to_graphhopper,
)
from routing.graph import haversine_m
from routing.rule_engine import CompiledModel

NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)

#   B ───────► D        A -> B -> D : north, then RIGHT turn (crosses traffic in India)
#   ▲          ▲        A -> C -> D : east, then LEFT turn
#   A ───────► C        both routes are the same length
NODES = {"A": (12.9700, 77.5900), "B": (12.9710, 77.5900), "C": (12.9700, 77.5910), "D": (12.9710, 77.5910)}


def edge(seg, a, b, rc=RoadClass.PRIMARY, **kw):
    kw.setdefault("speed_kmh", expected_speed_kmh(kw.get("max_speed_kmh"), traffic_calming=kw.get("traffic_calming", False)))
    return EdgeMeta(seg, a, b, rc, haversine_m(NODES[a], NODES[b]), geometry=(NODES[a], NODES[b]), **kw)


def square(**overrides):
    edges = {e.segment_id: e for e in (edge("AB", "A", "B"), edge("BD", "B", "D"),
                                       edge("AC", "A", "C"), edge("CD", "C", "D"))}
    for seg, kw in overrides.items():
        edges[seg] = replace(edges[seg], **kw)
    return edges


def service(edges, profile=CAR, restrictions=TurnRestrictions(), buckets=None):
    return RoutingService(LocalAStarRouter(RoadGraph(NODES, list(edges.values()))), edges,
                          profile=profile, turn_restrictions=restrictions, buckets=buckets)


def route(svc, **kw):
    return svc.route(NODES["A"], NODES["D"], NOW, **kw)


class TurnClassificationTests(unittest.TestCase):
    def test_classify(self):
        e = square()
        self.assertEqual(classify_turn(e["AB"], e["BD"]), Turn.RIGHT)
        self.assertEqual(classify_turn(e["AC"], e["CD"]), Turn.LEFT)
        back = edge("BA", "B", "A")
        self.assertEqual(classify_turn(e["AB"], back), Turn.U_TURN)
        straight = EdgeMeta("BX", "B", "X", RoadClass.PRIMARY, 100, geometry=(NODES["B"], (12.9720, 77.5900)))
        self.assertEqual(classify_turn(e["AB"], straight), Turn.STRAIGHT)

    def test_india_right_turn_costs_more(self):
        r = route(service(square()))
        self.assertEqual(r.segments, ["AC", "CD"])          # left turn preferred
        self.assertEqual(r.turn_s, CAR.turns.near_side)

    def test_banned_turn_is_never_taken(self):
        banned = TurnRestrictions(banned=frozenset({("AC", "CD")}))
        r = route(service(square(), restrictions=banned))
        self.assertEqual(r.segments, ["AB", "BD"])
        self.assertEqual(r.turn_s, CAR.turns.far_side)

    def test_only_restriction(self):
        only = TurnRestrictions(only={"AC": frozenset({"CX"})})
        self.assertEqual(route(service(square(), restrictions=only)).segments, ["AB", "BD"])


class PointDelayTests(unittest.TestCase):
    def test_signal_adds_time_not_priority(self):
        edges = square(AC={"end_delay_s": 30.0, "end_features": frozenset({"traffic_signals"})})
        svc = service(edges)
        self.assertEqual(CompiledModel(svc.model_for_request(NOW)).evaluate(edges["AC"]).priority, 1.0)
        r = route(svc)
        self.assertEqual(r.segments, ["AB", "BD"])           # 10 s right turn beats 30 s signal + 3 s left

    def test_eta_includes_delay_on_forced_route(self):
        edges = square(AC={"end_delay_s": 30.0}, AB={"road_access": RoadAccess.NO})
        r = route(service(edges))
        self.assertEqual(r.segments, ["AC", "CD"])
        self.assertEqual(r.point_delay_s, 30.0)
        driving = sum(edges[s].distance_m / (30 / 3.6) for s in r.segments)
        self.assertAlmostEqual(r.eta_s, driving + 30.0 + CAR.turns.near_side)

    def test_delay_at_destination_not_counted(self):
        edges = square(CD={"end_delay_s": 30.0}, BD={"end_delay_s": 30.0})
        r = route(service(edges))
        self.assertEqual(r.point_delay_s, 0.0)

    def test_speed_breaker_slows_slightly(self):
        edges = square(AC={"traffic_calming": True, "speed_kmh": expected_speed_kmh(None, traffic_calming=True)})
        svc = service(edges)
        self.assertAlmostEqual(CompiledModel(svc.model_for_request(NOW)).evaluate(edges["AC"]).speed_kmh, 27.0)


class PointDelayTelemetryTests(unittest.TestCase):
    """Waiting at a signal must not be learned as a slow road."""

    @staticmethod
    def samples(seg, distance_m, wait_s):
        observed = distance_m / (distance_m / (30 / 3.6) + wait_s) * 3.6   # drives at 30, then waits
        return [SpeedSample(seg, f"d{i}", f"t{i}", observed, NOW - timedelta(hours=1 + i % 48, days=i % 5))
                for i in range(60)]

    def test_signal_wait_is_not_a_slow_road(self):
        with_signal = square(AC={"end_delay_s": 30.0})
        rules = service(with_signal).refresh_telemetry(self.samples("AC", with_signal["AC"].distance_m, 30), [], NOW)
        self.assertEqual(rules, [])

    def test_same_wait_without_a_mapped_signal_is_flagged(self):
        plain = square()
        rules = service(plain).refresh_telemetry(self.samples("AC", plain["AC"].distance_m, 30), [], NOW)
        self.assertEqual([r.rule_id for r in rules], ["tele.speed.AC"])


class VehicleTests(unittest.TestCase):
    def test_vehicles_route_differently(self):
        shortcut = {"road_access": RoadAccess.NO}
        router = MultiVehicleRouter({
            VehicleType.CAR: service(square(), CAR),
            VehicleType.AUTO: service(square(AC=shortcut), AUTO),     # e.g. expressway barred to autos
        })
        self.assertEqual(router.route(VehicleType.CAR, NODES["A"], NODES["D"], now=NOW).segments, ["AC", "CD"])
        self.assertEqual(router.route(VehicleType.AUTO, NODES["A"], NODES["D"], now=NOW).segments, ["AB", "BD"])

    def test_bike_penalizes_residential_less(self):
        self.assertGreater(BIKE.priority[RoadClass.RESIDENTIAL], CAR.priority[RoadClass.RESIDENTIAL])
        bike_base = CompiledModel(baseline_model(BIKE)).evaluate(edge("AB", "A", "B", RoadClass.RESIDENTIAL))
        self.assertEqual(bike_base.priority, 0.7)

    def test_telemetry_is_split_by_vehicle(self):
        slow = [SpeedSample("AC", f"d{i}", f"t{i}", 8.0, NOW - timedelta(hours=1 + i, days=i % 4),
                            vehicle=VehicleType.BIKE) for i in range(60)]
        router = MultiVehicleRouter({v: service(square(), p) for v, p in
                                     ((VehicleType.CAR, CAR), (VehicleType.BIKE, BIKE))})
        rules = router.refresh_telemetry(slow, [], NOW)
        self.assertEqual(rules[VehicleType.CAR], [])
        self.assertEqual([r.rule_id for r in rules[VehicleType.BIKE]], ["tele.speed.AC"])


class GraphHopperTurnTests(unittest.TestCase):
    def test_turn_penalty_json(self):
        gh = to_graphhopper(baseline_model(CAR), {}, profile=CAR)
        self.assertEqual(gh["turn_penalty"][:2], [
            {"if": "change_angle >= 25 && change_angle < 150", "add": "10"},        # right = far side in India
            {"else_if": "-change_angle >= 25 && -change_angle < 150", "add": "3"},
        ])
        self.assertNotIn({"if": "traffic_calming", "multiply_by": 0.9}, gh["speed"])

    def test_extensions(self):
        gh = to_graphhopper(baseline_model(CAR), {}, profile=CAR, extensions=True)
        self.assertIn({"if": "traffic_calming", "multiply_by": 0.9}, gh["speed"])
        self.assertIn({"if": "prev_signal_ahead", "add": "30"}, gh["turn_penalty"])
        self.assertIn({"if": "prev_toll_booth_ahead", "add": "20"}, gh["turn_penalty"])


if __name__ == "__main__":
    unittest.main()
