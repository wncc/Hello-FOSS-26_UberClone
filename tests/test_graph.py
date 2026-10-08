"""Snapping to the road network (regressions found by the end-to-end UI test)."""
import unittest

from routing import EdgeMeta, RoadAccess, RoadClass
from routing.graph import graph_from_edges, haversine_m

#   Main loop A <-> B <-> C <-> A (two-way).  Island I1 <-> I2 joined to C only by a PRIVATE road.
P = {"A": (19.000, 72.800), "B": (19.000, 72.810), "C": (19.008, 72.805),
     "I1": (19.012, 72.805), "I2": (19.013, 72.806)}


def two_way(a, b, access=RoadAccess.YES, rc=RoadClass.RESIDENTIAL):
    return [EdgeMeta(f"{x}{y}", x, y, rc, haversine_m(P[x], P[y]), geometry=(P[x], P[y]), road_access=access)
            for x, y in ((a, b), (b, a))]


EDGES = [*two_way("A", "B"), *two_way("B", "C"), *two_way("C", "A"),
         *two_way("I1", "I2"), *two_way("C", "I1", RoadAccess.PRIVATE)]


class SnappingTests(unittest.TestCase):
    def test_never_snaps_onto_a_road_island(self):
        g = graph_from_edges(EDGES)
        self.assertNotIn("I1", g.main_nodes)
        self.assertEqual(g.nearest_node(P["I2"], "end"), "C")      # nearest *reachable* road instead

    def test_never_snaps_into_a_blocked_zone(self):
        g = graph_from_edges(EDGES, blocked={"BC", "CB", "CA", "AC"})
        self.assertNotIn(g.nearest_node(P["C"], "end"), {"C"})

    def test_far_from_any_road_is_outside_the_map(self):
        self.assertIsNone(graph_from_edges(EDGES).nearest_node((19.2, 72.9), "start"))


if __name__ == "__main__":
    unittest.main()
