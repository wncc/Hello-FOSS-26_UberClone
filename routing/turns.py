"""Turns: classification from geometry, per-vehicle costs, and turn restrictions.

India drives on the left: a right turn crosses oncoming traffic (far-side turn),
a left turn does not (near-side turn). Costs are time in seconds, added on top
of the edge cost and never scaled by road priority.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from .models import EdgeMeta
from .vehicles import TurnCosts

LEFT_HAND_TRAFFIC = True   # India
STRAIGHT_MAX_DEG = 25.0
U_TURN_MIN_DEG = 150.0


class Turn(str, Enum):
    STRAIGHT = "straight"
    LEFT = "left"
    RIGHT = "right"
    U_TURN = "u_turn"


def bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    x = math.sin(lon2 - lon1) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return math.degrees(math.atan2(x, y)) % 360.0


def turn_angle_deg(inbound: EdgeMeta, outbound: EdgeMeta) -> float:
    """Signed heading change in (-180, 180]; positive = clockwise = right turn."""
    if len(inbound.geometry) < 2 or len(outbound.geometry) < 2:
        return 0.0
    before = bearing_deg(inbound.geometry[-2], inbound.geometry[-1])
    after = bearing_deg(outbound.geometry[0], outbound.geometry[1])
    return (after - before + 540.0) % 360.0 - 180.0


def classify_turn(inbound: EdgeMeta, outbound: EdgeMeta) -> Turn:
    if outbound.to_node == inbound.from_node:
        return Turn.U_TURN
    angle = turn_angle_deg(inbound, outbound)
    if abs(angle) >= U_TURN_MIN_DEG:
        return Turn.U_TURN
    if abs(angle) < STRAIGHT_MAX_DEG:
        return Turn.STRAIGHT
    return Turn.RIGHT if angle > 0 else Turn.LEFT


@dataclass(frozen=True)
class TurnRestrictions:
    """From OSM `type=restriction` relations, resolved to segment pairs for one vehicle."""
    banned: frozenset[tuple[str, str]] = frozenset()
    only: dict[str, frozenset[str]] = field(default_factory=dict)  # inbound -> the only allowed outbounds

    def allows(self, inbound: str, outbound: str) -> bool:
        if (inbound, outbound) in self.banned:
            return False
        allowed = self.only.get(inbound)
        return allowed is None or outbound in allowed


NO_RESTRICTIONS = TurnRestrictions()


def turn_cost_s(inbound: EdgeMeta, outbound: EdgeMeta, costs: TurnCosts,
                restrictions: TurnRestrictions = NO_RESTRICTIONS, left_hand_traffic: bool = LEFT_HAND_TRAFFIC) -> float:
    if not restrictions.allows(inbound.segment_id, outbound.segment_id):
        return math.inf
    turn = classify_turn(inbound, outbound)
    if turn is Turn.STRAIGHT:
        return costs.straight
    if turn is Turn.U_TURN:
        return costs.u_turn
    near_side = (turn is Turn.LEFT) == left_hand_traffic
    return costs.near_side if near_side else costs.far_side


@dataclass(frozen=True)
class TurnModel:
    costs: TurnCosts
    restrictions: TurnRestrictions = NO_RESTRICTIONS
    left_hand_traffic: bool = LEFT_HAND_TRAFFIC

    def cost_s(self, inbound: EdgeMeta, outbound: EdgeMeta) -> float:
        return turn_cost_s(inbound, outbound, self.costs, self.restrictions, self.left_hand_traffic)
