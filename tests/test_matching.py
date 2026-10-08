import json
import random
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from matching import GridIndex, MatchingConfig, RouterEta, StraightLineEta, haversine_km, run_cycle
from matching.server import cycle_once
from routing import CAR, EdgeMeta, LocalAStarRouter, MultiVehicleRouter, RoadClass, RoadGraph, RoutingService, VehicleType
from routing.graph import haversine_m

NOW = datetime(2026, 10, 7, 9, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)
NO_RESERVE = MatchingConfig(reserve_ratio=0.0)


def driver(i, lat, lng, status="free", rider=None, **kw):
    return {"id": i, "lat": lat, "lng": lng, "status": status, "riderId": rider, **kw}


def rider(i, lat, lng, status="ping_pending", **kw):
    return {"id": i, "lat": lat, "lng": lng, "status": status, "driverId": None, "driverIds": [], **kw}


def cycle(drivers, riders, config=NO_RESERVE, eta=None, now=NOW, seed=1):
    return run_cycle({"drivers": drivers, "riders": riders}, now, eta, config, random.Random(seed))


class OriginalBehaviourTests(unittest.TestCase):
    def test_pings_up_to_three_drivers_within_radius(self):
        drivers = [driver(f"D{i}", 12.97 + i * 0.001, 77.59) for i in range(5)] + [driver("FAR", 13.10, 77.59)]
        riders = [rider("R1", 12.97, 77.59)]
        cycle(drivers, riders)
        pinged = [d["id"] for d in drivers if d["status"] == "pinged"]
        self.assertEqual(len(pinged), 3)
        self.assertNotIn("FAR", pinged)
        self.assertEqual(riders[0]["status"], "driver_pinged")
        self.assertEqual(sorted(riders[0]["driverIds"]), sorted(pinged))
        self.assertTrue(all(d["riderId"] == "R1" and d["pingedAt"] == NOW_MS
                            for d in drivers if d["status"] == "pinged"))

    def test_a_driver_is_pinged_for_one_rider_only(self):
        drivers = [driver("D1", 12.97, 77.59)]
        riders = [rider("R1", 12.97, 77.591), rider("R2", 12.97, 77.592)]
        cycle(drivers, riders)
        self.assertEqual(sum(r["status"] == "driver_pinged" for r in riders), 1)

    def test_reserve_holds_back_a_fifth(self):
        drivers = [driver(f"D{i}", 12.97 + i * 0.0005, 77.59) for i in range(10)]
        riders = [rider(f"R{i}", 12.97, 77.59 + i * 0.0005) for i in range(10)]
        cycle(drivers, riders, MatchingConfig(max_drivers_per_rider=1))
        self.assertEqual(sum(d["status"] == "free" for d in drivers), 2)

    def test_nearest_acceptor_wins(self):
        drivers = [driver("NEAR", 12.971, 77.59, "accepted", "R1"), driver("FAR", 12.98, 77.59, "accepted", "R1")]
        riders = [rider("R1", 12.97, 77.59, "driver_pinged", driverIds=["NEAR", "FAR"])]
        result = cycle(drivers, riders)
        self.assertEqual(result.accepted, [{"riderId": "R1", "driverId": "NEAR"}])
        self.assertEqual((drivers[1]["status"], drivers[1]["riderId"]), ("free", None))
        self.assertEqual((riders[0]["status"], riders[0]["driverIds"]), ("accepted", []))


class BugFixTests(unittest.TestCase):
    def test_other_pinged_drivers_released_when_rider_matched(self):
        drivers = [driver("A", 12.971, 77.59, "accepted", "R1"), driver("B", 12.972, 77.59, "pinged", "R1", pingedAt=NOW_MS)]
        riders = [rider("R1", 12.97, 77.59, "driver_pinged", driverIds=["A", "B"])]
        cycle(drivers, riders)
        self.assertEqual(drivers[1]["status"], "free")

    def test_unanswered_ping_times_out_and_rider_is_repinged(self):
        old = NOW_MS - 30_000
        drivers = [driver("A", 12.971, 77.59, "pinged", "R1", pingedAt=old), driver("B", 12.972, 77.59)]
        riders = [rider("R1", 12.97, 77.59, "driver_pinged", driverIds=["A"])]
        result = cycle(drivers, riders, MatchingConfig(reserve_ratio=0, max_drivers_per_rider=1, selection="nearest"))
        self.assertEqual(result.stats["pings_timed_out"], 1)
        self.assertEqual(riders[0]["status"], "driver_pinged")      # re-pinged in the same cycle
        self.assertEqual(riders[0]["driverIds"], ["A"])             # A is free again and nearest

    def test_fresh_ping_is_kept(self):
        drivers = [driver("A", 12.971, 77.59, "pinged", "R1", pingedAt=NOW_MS - 5_000)]
        riders = [rider("R1", 12.97, 77.59, "driver_pinged", driverIds=["A"])]
        cycle(drivers, riders)
        self.assertEqual((drivers[0]["status"], riders[0]["status"]), ("pinged", "driver_pinged"))

    def test_rider_whose_drivers_all_rejected_goes_back_to_pending(self):
        drivers = [driver("A", 13.5, 77.59)]                         # backend set A free (rejected); now far away
        riders = [rider("R1", 12.97, 77.59, "driver_pinged", driverIds=["A"])]
        result = cycle(drivers, riders)
        self.assertEqual((riders[0]["status"], riders[0]["driverIds"]), ("ping_pending", []))
        self.assertEqual(result.stats["riders_repinged"], 1)

    def test_confirmed_match_is_never_reassigned(self):
        drivers = [driver("FIRST", 12.98, 77.59, "accepted", "R1"), driver("LATE_BUT_NEAR", 12.9701, 77.59, "accepted", "R1")]
        riders = [rider("R1", 12.97, 77.59, "accepted", driverId="FIRST")]
        cycle(drivers, riders)
        self.assertEqual(riders[0]["driverId"], "FIRST")
        self.assertEqual(drivers[1]["status"], "free")

    def test_driver_released_when_rider_cancelled(self):
        drivers = [driver("A", 12.97, 77.59, "accepted", "GONE"), driver("B", 12.97, 77.59, "pinged", "GONE", pingedAt=NOW_MS)]
        cycle(drivers, [])
        self.assertEqual([d["status"] for d in drivers], ["free", "free"])

    def test_rider_requeued_when_matched_driver_cancels(self):
        drivers = [driver("A", 12.97, 77.59)]                       # backend freed A after it cancelled
        riders = [rider("R1", 12.97, 77.591, "accepted", driverId="A")]
        cycle(drivers, riders)
        self.assertEqual(riders[0]["status"], "driver_pinged")      # back in the queue and re-pinged
        self.assertIsNone(riders[0]["driverId"])

    def test_vehicle_type_must_match(self):
        drivers = [driver("CAR", 12.97, 77.59), driver("AUTO", 12.971, 77.59, vehicle="auto_rickshaw")]
        riders = [rider("R1", 12.97, 77.59, vehicle="auto_rickshaw")]
        cycle(drivers, riders)
        self.assertEqual(riders[0]["driverIds"], ["AUTO"])
        self.assertEqual(drivers[0]["status"], "free")

    def test_excluded_drivers_are_not_pinged_again(self):
        drivers = [driver("REJECTED_IT", 12.97, 77.59), driver("OTHER", 12.975, 77.59)]
        riders = [rider("R1", 12.97, 77.59, excludedDriverIds=["REJECTED_IT"])]
        cycle(drivers, riders)
        self.assertEqual(riders[0]["driverIds"], ["OTHER"])

    def test_bad_records_are_skipped_not_fatal(self):
        drivers = [driver("BAD", None, 77.59), driver("STR", "12.9", 77.59), driver("UFO", 12.97, 77.59, vehicle="ufo"),
                   driver("OK", 12.97, 77.59)]
        riders = [rider("R1", 12.97, 77.59)]
        result = cycle(drivers, riders)
        self.assertEqual(result.stats["invalid_records"], 3)
        self.assertEqual(riders[0]["driverIds"], ["OK"])
        self.assertEqual(drivers[0]["status"], "free")              # untouched

    def test_unknown_fields_pass_through(self):
        drivers = [driver("A", 12.97, 77.59, name="Ravi", rating=4.8)]
        cycle(drivers, [])
        self.assertEqual((drivers[0]["name"], drivers[0]["rating"]), ("Ravi", 4.8))


#   N (driver NEAR, across the river) ── long bridge detour ── R (rider)
#   E (driver EAST) ── short direct road ── R
RIVER = {"R": (12.970, 77.590), "N": (12.975, 77.590), "B1": (12.975, 77.620), "B2": (12.970, 77.620),
         "E": (12.970, 77.600)}


def river_router():
    def edge(a, b):
        return EdgeMeta(f"{a}{b}", a, b, RoadClass.PRIMARY, haversine_m(RIVER[a], RIVER[b]), geometry=(RIVER[a], RIVER[b]))
    edges = {e.segment_id: e for e in (edge("N", "B1"), edge("B1", "B2"), edge("B2", "R"), edge("E", "R"))}
    svc = RoutingService(LocalAStarRouter(RoadGraph(RIVER, list(edges.values()))), edges, profile=CAR)
    return MultiVehicleRouter({VehicleType.CAR: svc})


class RoutingIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.eta = RouterEta(river_router())
        self.config = MatchingConfig(reserve_ratio=0, max_drivers_per_rider=1, selection="nearest")

    def _drivers(self, status="free", rider_id=None):
        return [driver("NEAR", *RIVER["N"], status, rider_id), driver("EAST", *RIVER["E"], status, rider_id)]

    def test_straight_line_picks_the_driver_across_the_river(self):
        riders = [rider("R1", *RIVER["R"])]
        cycle(self._drivers(), riders, self.config, eta=StraightLineEta())
        self.assertEqual(riders[0]["driverIds"], ["NEAR"])

    def test_road_eta_picks_the_driver_who_can_actually_get_there(self):
        riders = [rider("R1", *RIVER["R"])]
        cycle(self._drivers(), riders, self.config, eta=self.eta)
        self.assertEqual(riders[0]["driverIds"], ["EAST"])

    def test_conflict_resolved_by_road_eta(self):
        riders = [rider("R1", *RIVER["R"], "driver_pinged", driverIds=["NEAR", "EAST"])]
        result = cycle(self._drivers("accepted", "R1"), riders, self.config, eta=self.eta)
        self.assertEqual(result.accepted, [{"riderId": "R1", "driverId": "EAST"}])

    def test_drivers_beyond_max_pickup_eta_are_skipped(self):
        riders = [rider("R1", *RIVER["R"])]
        drivers = [driver("NEAR", *RIVER["N"])]                     # ~14 min by road
        tight = MatchingConfig(reserve_ratio=0, max_pickup_eta_s=5 * 60)
        result = cycle(drivers, riders, tight, eta=self.eta)
        self.assertEqual(riders[0]["status"], "ping_pending")
        self.assertEqual(result.stats["riders_without_driver"], 1)

    def test_vehicle_without_a_router_gets_no_driver(self):
        riders = [rider("R1", *RIVER["R"], vehicle="bike")]
        cycle([driver("B", *RIVER["E"], vehicle="bike")], riders, self.config, eta=self.eta)
        self.assertEqual(riders[0]["status"], "ping_pending")


class GridIndexTests(unittest.TestCase):
    def test_matches_brute_force(self):
        rng = random.Random(3)
        pts = {f"p{i}": (12.9 + rng.random() * 0.2, 77.5 + rng.random() * 0.2) for i in range(500)}
        index = GridIndex()
        for k, p in pts.items():
            index.add(k, p)
        center = (13.0, 77.6)
        expected = sorted(k for k, p in pts.items() if haversine_km(center, p) <= 4.0)
        self.assertEqual(sorted(k for k, _ in index.within(center, 4.0)), expected)


class _FakeBackend(BaseHTTPRequestHandler):
    state: dict = {}
    updates: list = []

    def do_GET(self):
        body = json.dumps(self.state).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        self.updates.append(json.loads(self.rfile.read(length)))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


class ServerTests(unittest.TestCase):
    def test_cycle_against_http_backend(self):
        _FakeBackend.state = {"drivers": [driver("D1", 12.97, 77.59)], "riders": [rider("R1", 12.971, 77.59)]}
        _FakeBackend.updates = []
        server = HTTPServer(("127.0.0.1", 0), _FakeBackend)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            result = cycle_once(f"http://127.0.0.1:{server.server_port}", None, NO_RESERVE)
        finally:
            server.shutdown()
        self.assertEqual(result.stats["pinged_riders"], 1)
        pushed = _FakeBackend.updates[0]
        self.assertEqual((pushed["drivers"][0]["status"], pushed["riders"][0]["driverIds"]), ("pinged", ["D1"]))


if __name__ == "__main__":
    unittest.main()
