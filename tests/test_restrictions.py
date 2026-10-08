import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from routing import (
    IST, EdgeMeta, LocalAStarRouter, MultiVehicleRouter, RestrictedZone, RoadAccess, RoadClass, RoadGraph,
    RouteOptions, RoutingService, SpeedLimitSource, TimeBuckets, Toll, VehicleType, ZoneKind,
    expected_speed_kmh, to_graphhopper,
)
from routing.graph import haversine_m
from routing.osm_import import (
    INDIA_M1, extract, load, parse_access, parse_conditional, parse_maxspeed, parse_toll, save,
)
from routing.rule_engine import CompiledModel

NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
BUCKETS = TimeBuckets(IST)
WEEKDAY_9AM = datetime(2026, 9, 29, 9, 15, tzinfo=IST)   # Tuesday
WEEKDAY_2AM = datetime(2026, 9, 29, 2, 15, tzinfo=IST)


class TagParsingTests(unittest.TestCase):
    def test_maxspeed(self):
        cases = {"50": 50, "30 mph": 30 * 1.609344, "IN:urban": 70, "IN:zone30": 30, "walk": 7,
                 "40;60": 40, "none": None, "signals": None, "DE:urban": None, "fast": None}
        for value, expected in cases.items():
            with self.subTest(value=value):
                got = parse_maxspeed(value)
                self.assertEqual(got, expected) if expected is None else self.assertAlmostEqual(got, expected)

    def test_legal_defaults_and_city_cap(self):
        self.assertEqual(INDIA_M1.default_for(RoadClass.MOTORWAY, False), 120)
        self.assertEqual(INDIA_M1.default_for(RoadClass.TRUNK, True), 100)
        self.assertEqual(INDIA_M1.default_for(RoadClass.TRUNK, False), 70)
        capped = replace(INDIA_M1, city_cap_kmh=50)
        self.assertEqual(capped.default_for(RoadClass.PRIMARY, True), 50)
        self.assertEqual(capped.default_for(RoadClass.MOTORWAY, False), 120)

    def test_access_most_specific_wins(self):
        self.assertEqual(parse_access({"access": "no", "motorcar": "yes"}), RoadAccess.YES)
        self.assertEqual(parse_access({"access": "private"}), RoadAccess.PRIVATE)
        self.assertEqual(parse_access({"motor_vehicle": "destination"}), RoadAccess.DESTINATION)
        self.assertEqual(parse_access({"access": "customers"}), RoadAccess.DESTINATION)
        self.assertEqual(parse_access({}), RoadAccess.YES)

    def test_toll(self):
        self.assertEqual(parse_toll({"toll": "yes"}), Toll.ALL)
        self.assertEqual(parse_toll({"toll": "yes", "toll:motorcar": "no"}), Toll.NO)
        self.assertEqual(parse_toll({"toll:hgv": "yes"}), Toll.HGV)
        self.assertEqual(parse_toll({}), Toll.MISSING)

    def test_conditional(self):
        self.assertEqual(parse_conditional({"motor_vehicle:conditional": "no @ (Mo-Fr 07:00-09:00,17:00-19:00)"}),
                         (frozenset({7, 8, 17, 18}), True))
        overnight, ok = parse_conditional({"access:conditional": "no @ (22:00-02:00)"})
        self.assertTrue(ok)
        self.assertEqual(overnight, frozenset(d * 24 + h for d in range(3) for h in (22, 23, 0, 1)))
        self.assertEqual(parse_conditional({"access:conditional": "no @ (Sa)"}),
                         (frozenset(range(24, 48)), True))
        self.assertEqual(parse_conditional({"access:conditional": "no @ (Jan-Mar)"}), (None, False))
        self.assertEqual(parse_conditional({"access:conditional": "no @ (weight>7)"}), (None, False))
        self.assertEqual(parse_conditional({"access:conditional": "destination @ (Mo-Fr 08:00-10:00)"}),
                         (None, True))


OSM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
 <node id="1" lat="12.9700" lon="77.5900" version="1"/>
 <node id="2" lat="12.9710" lon="77.5900" version="1"><tag k="traffic_calming" v="bump"/></node>
 <node id="3" lat="12.9720" lon="77.5900" version="1"><tag k="highway" v="traffic_signals"/>
  <tag k="traffic_signals:direction" v="forward"/></node>
 <node id="4" lat="12.9730" lon="77.5900" version="1"/>
 <node id="5" lat="12.9740" lon="77.5900" version="1"/>
 <node id="6" lat="12.9750" lon="77.5900" version="1"><tag k="barrier" v="toll_booth"/></node>
 <node id="7" lat="12.9760" lon="77.5900" version="1"/>
 <node id="8" lat="12.9770" lon="77.5900" version="1"/>
 <node id="9" lat="12.9800" lon="77.6000" version="1"/>
 <node id="10" lat="12.9800" lon="77.6100" version="1"/>
 <node id="11" lat="12.9900" lon="77.6100" version="1"/>
 <node id="12" lat="12.9900" lon="77.6000" version="1"/>
 <node id="13" lat="12.9720" lon="77.5910" version="1"/>
 <way id="100" version="1"><nd ref="1"/><nd ref="2"/><nd ref="3"/>
  <tag k="highway" v="primary"/><tag k="maxspeed" v="50"/></way>
 <way id="101" version="1"><nd ref="3"/><nd ref="4"/><tag k="highway" v="motorway"/></way>
 <way id="102" version="1"><nd ref="4"/><nd ref="5"/><tag k="highway" v="trunk"/><tag k="oneway" v="yes"/></way>
 <way id="103" version="1"><nd ref="5"/><nd ref="6"/><tag k="highway" v="residential"/><tag k="access" v="private"/></way>
 <way id="104" version="1"><nd ref="6"/><nd ref="7"/><tag k="highway" v="primary"/><tag k="toll" v="yes"/>
  <tag k="maxspeed:forward" v="40"/><tag k="maxspeed:backward" v="60"/></way>
 <way id="105" version="1"><nd ref="7"/><nd ref="8"/><tag k="highway" v="living_street"/><tag k="maxspeed" v="20"/>
  <tag k="motor_vehicle:conditional" v="no @ (Mo-Fr 08:00-10:00)"/></way>
 <way id="106" version="1"><nd ref="1"/><nd ref="8"/><tag k="highway" v="footway"/></way>
 <way id="107" version="1"><nd ref="9"/><nd ref="10"/><nd ref="11"/><nd ref="12"/><nd ref="9"/>
  <tag k="landuse" v="military"/><tag k="name" v="Cantonment"/></way>
 <way id="108" version="1"><nd ref="3"/><nd ref="13"/><tag k="highway" v="secondary"/></way>
 <relation id="200" version="1">
  <member type="way" ref="100" role="from"/><member type="node" ref="3" role="via"/>
  <member type="way" ref="108" role="to"/>
  <tag k="type" v="restriction"/><tag k="restriction" v="no_right_turn"/><tag k="except" v="motorcycle"/>
 </relation>
</osm>
"""


class OsmImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(cls.tmp.name, "city.osm")
        with open(path, "w", encoding="utf-8") as f:
            f.write(OSM_XML)
        cls.ex = extract(path)
        cls.car, cls.bike, cls.auto = (cls.ex.edges[v] for v in (VehicleType.CAR, VehicleType.BIKE, VehicleType.AUTO))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_segments_and_directions(self):
        e = self.car
        self.assertIn("100:1:2", e)
        self.assertIn("100:2:1", e)          # two-way
        self.assertIn("101:3:4", e)
        self.assertNotIn("101:4:3", e)       # motorway implies oneway
        self.assertNotIn("102:5:4", e)       # oneway=yes
        self.assertFalse(any(k.startswith("106:") for k in e))  # footway ignored
        self.assertAlmostEqual(e["100:1:2"].distance_m, 111, delta=2)

    def test_car_speed_limits(self):
        e = self.car
        self.assertEqual((e["100:1:2"].max_speed_kmh, e["100:1:2"].max_speed_source), (50, SpeedLimitSource.SIGN))
        self.assertEqual((e["101:3:4"].max_speed_kmh, e["101:3:4"].max_speed_source),
                         (120, SpeedLimitSource.LEGAL_DEFAULT))
        self.assertEqual(e["102:4:5"].max_speed_kmh, 100)       # divided (oneway) trunk
        self.assertEqual(e["104:6:7"].max_speed_kmh, 40)        # maxspeed:forward
        self.assertEqual(e["104:7:6"].max_speed_kmh, 60)        # maxspeed:backward
        self.assertEqual(e["105:7:8"].speed_kmh, 20)            # legal limit below uniform speed

    def test_vehicle_specific_limits_access_and_tolls(self):
        self.assertEqual(self.bike["101:3:4"].max_speed_kmh, 80)          # motorcycle expressway limit
        self.assertEqual(self.bike["103:5:6"].max_speed_kmh, 60)          # motorcycle "other roads"
        self.assertEqual(self.auto["102:4:5"].max_speed_kmh, 50)          # three-wheeler everywhere
        self.assertEqual(self.auto["104:7:6"].max_speed_kmh, 50)          # sign 60, capped at category max
        self.assertEqual(self.auto["101:3:4"].road_access, RoadAccess.NO)  # three-wheelers barred from expressways
        self.assertEqual(self.car["104:6:7"].toll, Toll.ALL)
        self.assertEqual(self.bike["104:6:7"].toll, Toll.NO)               # two-wheelers exempt

    def test_point_delays_and_speed_breakers(self):
        e = self.car
        self.assertEqual((e["100:2:3"].end_features, e["100:2:3"].end_delay_s), (frozenset({"traffic_signals"}), 30))
        self.assertEqual(e["108:13:3"].end_delay_s, 0)          # signal faces the way's forward direction only
        self.assertEqual(e["103:5:6"].end_features, frozenset({"toll_booth"}))
        self.assertEqual((e["103:5:6"].end_delay_s, self.bike["103:5:6"].end_delay_s), (20, 5))
        self.assertTrue(e["100:1:2"].traffic_calming)           # bump at node 2
        self.assertEqual(e["100:1:2"].speed_kmh, 27)            # 30 x 0.9
        self.assertFalse(e["100:2:3"].traffic_calming)

    def test_turn_restrictions_per_vehicle(self):
        car_tr = self.ex.turn_restrictions[VehicleType.CAR]
        self.assertFalse(car_tr.allows("100:2:3", "108:3:13"))
        self.assertTrue(car_tr.allows("100:2:3", "101:3:4"))
        self.assertTrue(self.ex.turn_restrictions[VehicleType.BIKE].allows("100:2:3", "108:3:13"))  # except=motorcycle
        self.assertFalse(self.ex.turn_restrictions[VehicleType.AUTO].allows("100:2:3", "108:3:13"))

    def test_access_toll_conditional_zone(self):
        e = self.car
        self.assertEqual(e["103:5:6"].road_access, RoadAccess.PRIVATE)
        self.assertEqual(e["105:7:8"].no_access_buckets, frozenset({8, 9}))
        self.assertEqual(len(self.ex.zones), 1)
        zone = self.ex.zones[0]
        self.assertEqual((zone.kind, zone.name, zone.source), (ZoneKind.NO_ENTRY, "Cantonment", "osm"))
        self.assertTrue(zone.contains((12.985, 77.605)))
        self.assertFalse(zone.contains((12.975, 77.605)))

    def test_stats(self):
        s = self.ex.stats
        self.assertEqual(s["ways"], 7)
        self.assertEqual(s["car.access.PRIVATE"], 1)
        self.assertEqual(s["car.toll.ALL"], 1)
        self.assertEqual(s["car.conditional.parsed"], 1)
        self.assertEqual(s["zones.no_entry"], 1)
        self.assertEqual((s["nodes.traffic_signals"], s["nodes.toll_booth"], s["nodes.traffic_calming"]), (1, 1, 1))

    def test_json_round_trip_feeds_routing_service(self):
        path = os.path.join(self.tmp.name, "roads.json")
        save(self.ex, path)
        loaded = load(path)
        self.assertEqual(loaded.edges, self.ex.edges)
        self.assertEqual(loaded.zones, self.ex.zones)
        self.assertEqual(loaded.turn_restrictions, self.ex.turn_restrictions)
        router = MultiVehicleRouter.local(loaded, buckets=BUCKETS)
        self.assertEqual(set(router.services), set(VehicleType))


#   A ── short primary (via S) ── C
#   A ── long primary (via L) ─── C
NODES = {"A": (12.9700, 77.5900), "S": (12.9705, 77.5950), "L": (12.9750, 77.5950), "C": (12.9700, 77.6000)}


def _edge(seg, a, b, **kw):
    return EdgeMeta(seg, a, b, RoadClass.PRIMARY, haversine_m(NODES[a], NODES[b]),
                    geometry=(NODES[a], NODES[b]), **kw)


def service(short_kw=None, zones=()):
    short_kw = short_kw or {}
    edges = [_edge("AS", "A", "S", **short_kw), _edge("SC", "S", "C", **short_kw),
             _edge("AL", "A", "L"), _edge("LC", "L", "C")]
    return RoutingService(LocalAStarRouter(RoadGraph(NODES, edges)), {e.segment_id: e for e in edges},
                          buckets=BUCKETS, zones=list(zones))


def via(svc, **kw):
    return svc.route(NODES["A"], NODES["C"], NOW, **kw).segments[0]


class RestrictionRoutingTests(unittest.TestCase):
    def test_unrestricted_takes_short_road(self):
        self.assertEqual(via(service()), "AS")

    def test_private_and_delivery_roads_are_blocked(self):
        for access in (RoadAccess.PRIVATE, RoadAccess.NO, RoadAccess.DELIVERY):
            with self.subTest(access=access):
                self.assertEqual(via(service({"road_access": access})), "AL")

    def test_destination_road_not_used_as_shortcut(self):
        self.assertEqual(via(service({"road_access": RoadAccess.DESTINATION})), "AL")

    def test_tolls_reported_and_avoidable(self):
        svc = service({"toll": Toll.ALL})
        result = svc.route(NODES["A"], NODES["C"], NOW)
        self.assertEqual(result.toll_segments, ["AS", "SC"])
        toll_free = svc.route(NODES["A"], NODES["C"], NOW, options=RouteOptions(avoid_tolls=True))
        self.assertEqual((toll_free.segments[0], toll_free.toll_segments), ("AL", []))

    def test_time_based_closure(self):
        svc = service({"no_access_buckets": frozenset({9})})
        self.assertEqual(via(svc, depart_at=WEEKDAY_9AM), "AL")
        self.assertEqual(via(svc, depart_at=WEEKDAY_2AM), "AS")

    def test_no_entry_zone(self):
        box = ((12.9700, 77.5945), (12.9712, 77.5945), (12.9712, 77.5955), (12.9700, 77.5955))
        self.assertEqual(via(service(zones=[RestrictedZone("mil1", ZoneKind.NO_ENTRY, box)])), "AL")
        timed = RestrictedZone("market", ZoneKind.AVOID, box, active_buckets=frozenset({9}))
        self.assertEqual(via(service(zones=[timed]), depart_at=WEEKDAY_9AM), "AL")
        self.assertEqual(via(service(zones=[timed]), depart_at=WEEKDAY_2AM), "AS")

    def test_speed_limit_below_uniform_speed(self):
        svc = service({"max_speed_kmh": 10.0, "speed_kmh": expected_speed_kmh(10.0)})
        ev = CompiledModel(svc.model_for_request(NOW)).evaluate(svc.edges["AS"])
        self.assertEqual(ev.speed_kmh, 10)
        self.assertEqual(via(svc), "AL")

    def test_speed_limit_above_uniform_speed_changes_nothing(self):
        svc = service({"max_speed_kmh": 100.0})
        self.assertEqual(CompiledModel(svc.model_for_request(NOW)).evaluate(svc.edges["AS"]).speed_kmh, 30)

    def test_inconsistent_expected_speed_rejected(self):
        with self.assertRaises(ValueError):
            service({"max_speed_kmh": 10.0})   # speed_kmh left at 30

    def test_time_rules_require_buckets(self):
        edges = {"AS": _edge("AS", "A", "S", no_access_buckets=frozenset({9}))}
        with self.assertRaises(ValueError):
            RoutingService(LocalAStarRouter(RoadGraph(NODES, list(edges.values()))), edges)

    def test_graphhopper_payload(self):
        box = ((12.97, 77.59), (12.98, 77.59), (12.98, 77.60))
        svc = service(zones=[RestrictedZone("mil1", ZoneKind.NO_ENTRY, box, source="osm")])
        gh = to_graphhopper(svc.model_for_request(NOW, options=RouteOptions(avoid_tolls=True)), svc.edges)
        self.assertIn({"if": "true", "limit_to": "max_speed"}, gh["speed"])
        self.assertIn({"if": "road_access == PRIVATE", "multiply_by": 0.0}, gh["priority"])
        self.assertIn({"if": "toll == ALL", "multiply_by": 0.1}, gh["priority"])
        self.assertIn({"if": "in_zone_mil1", "multiply_by": 0.0}, gh["priority"])
        ring = gh["areas"]["features"][0]["geometry"]["coordinates"][0]
        self.assertEqual((ring[0], ring[-1]), ([77.59, 12.97], [77.59, 12.97]))


if __name__ == "__main__":
    unittest.main()
