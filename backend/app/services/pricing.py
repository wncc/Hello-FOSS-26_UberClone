"""Fares, in paise. PLACEHOLDER rates: set real market rates per city before launch."""
from __future__ import annotations

from dataclasses import dataclass

from routing import VehicleType


@dataclass(frozen=True)
class FareCard:
    base_paise: int
    per_km_paise: int
    per_min_paise: int
    minimum_paise: int
    booking_fee_paise: int = 0


@dataclass(frozen=True)
class FareBreakdown:
    base_paise: int
    distance_paise: int
    duration_paise: int
    booking_fee_paise: int
    minimum_topup_paise: int
    rounding_paise: int
    total_paise: int


FARE_CARDS: dict[VehicleType, FareCard] = {
    VehicleType.BIKE: FareCard(base_paise=2000, per_km_paise=800, per_min_paise=50, minimum_paise=3000),
    VehicleType.AUTO: FareCard(base_paise=3000, per_km_paise=1300, per_min_paise=100, minimum_paise=4000),
    VehicleType.CAR: FareCard(base_paise=5000, per_km_paise=1600, per_min_paise=150, minimum_paise=8000,
                              booking_fee_paise=1000),
}


def fare_breakdown(vehicle: VehicleType, distance_m: float, duration_s: float,
                   cards: dict[VehicleType, FareCard] = FARE_CARDS) -> FareBreakdown:
    card = cards[vehicle]
    base = card.base_paise
    dist = int(round(card.per_km_paise * distance_m / 1000.0))
    dur = int(round(card.per_min_paise * duration_s / 60.0))
    booking = card.booking_fee_paise
    subtotal = base + dist + dur + booking
    min_topup = max(0, card.minimum_paise - subtotal)
    before_rounding = subtotal + min_topup
    total = int(-(-before_rounding // 100) * 100)
    rounding = total - before_rounding
    return FareBreakdown(
        base_paise=base,
        distance_paise=dist,
        duration_paise=dur,
        booking_fee_paise=booking,
        minimum_topup_paise=min_topup,
        rounding_paise=rounding,
        total_paise=total,
    )


def fare_paise(vehicle: VehicleType, distance_m: float, duration_s: float,
               cards: dict[VehicleType, FareCard] = FARE_CARDS) -> int:
    return fare_breakdown(vehicle, distance_m, duration_s, cards).total_paise
