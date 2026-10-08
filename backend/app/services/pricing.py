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


FARE_CARDS: dict[VehicleType, FareCard] = {
    VehicleType.BIKE: FareCard(base_paise=2000, per_km_paise=800, per_min_paise=50, minimum_paise=3000),
    VehicleType.AUTO: FareCard(base_paise=3000, per_km_paise=1300, per_min_paise=100, minimum_paise=4000),
    VehicleType.CAR: FareCard(base_paise=5000, per_km_paise=1600, per_min_paise=150, minimum_paise=8000,
                              booking_fee_paise=1000),
}


def fare_paise(vehicle: VehicleType, distance_m: float, duration_s: float,
               cards: dict[VehicleType, FareCard] = FARE_CARDS) -> int:
    card = cards[vehicle]
    raw = (card.base_paise + card.per_km_paise * distance_m / 1000.0
           + card.per_min_paise * duration_s / 60.0 + card.booking_fee_paise)
    # Round up to the next whole rupee, as riders see whole-rupee fares.
    rupees = -(-max(raw, card.minimum_paise) // 100)
    return int(rupees * 100)
