from __future__ import annotations

import pytest

from routing import VehicleType
from backend.app.services.pricing import FARE_CARDS, fare_breakdown, fare_paise


def test_breakdown_parts_always_sum_to_total():
    """Verify that all parts always add up to total_paise across vehicles, distances, and durations."""
    distances = [0, 100, 500, 1234, 2500, 5000, 10789, 25000]
    durations = [0, 30, 90, 300, 725, 1200, 2450, 5400]

    for vehicle in VehicleType:
        for dist in distances:
            for dur in durations:
                bd = fare_breakdown(vehicle, dist, dur)
                parts_sum = (
                    bd.base_paise
                    + bd.distance_paise
                    + bd.duration_paise
                    + bd.booking_fee_paise
                    + bd.minimum_topup_paise
                    + bd.rounding_paise
                )
                assert parts_sum == bd.total_paise, (
                    f"Mismatch for {vehicle.value} dist={dist} dur={dur}: parts sum {parts_sum} != total {bd.total_paise}"
                )
                assert bd.total_paise == fare_paise(vehicle, dist, dur)
                assert bd.total_paise % 100 == 0, f"Total fare {bd.total_paise} must be whole rupee (multiples of 100 paise)"
                assert bd.rounding_paise >= 0
                assert bd.minimum_topup_paise >= 0


def test_minimum_fare_topup():
    """Very short trips should have a positive minimum_topup_paise and hit the card minimum."""
    card = FARE_CARDS[VehicleType.BIKE]
    bd = fare_breakdown(VehicleType.BIKE, distance_m=0, duration_s=0)
    assert bd.base_paise == card.base_paise
    assert bd.distance_paise == 0
    assert bd.duration_paise == 0
    assert bd.booking_fee_paise == card.booking_fee_paise
    assert bd.minimum_topup_paise == card.minimum_paise - card.base_paise
    assert bd.total_paise == card.minimum_paise


def test_car_booking_fee_included():
    """Car fare includes booking fee."""
    card = FARE_CARDS[VehicleType.CAR]
    bd = fare_breakdown(VehicleType.CAR, distance_m=5000, duration_s=600)
    assert bd.booking_fee_paise == card.booking_fee_paise
    assert bd.booking_fee_paise > 0
    assert bd.total_paise >= card.minimum_paise


def test_rounding_up_to_next_rupee():
    """Fares with fractional paise round up to the next rupee, accounted in rounding_paise."""
    # Bike per min is 50 paise. 30 seconds = 25 paise.
    # Base: 2000, dist (2000m * 800 / 1000 = 1600), time: 25 paise -> subtotal = 3625 paise.
    # Rounded up to 3700 paise. rounding_paise should be 75 paise.
    bd = fare_breakdown(VehicleType.BIKE, distance_m=2000, duration_s=30)
    assert bd.total_paise == 3700
    assert bd.base_paise == 2000
    assert bd.distance_paise == 1600
    assert bd.duration_paise == 25
    assert bd.minimum_topup_paise == 0
    assert bd.rounding_paise == 75
    assert (
        bd.base_paise
        + bd.distance_paise
        + bd.duration_paise
        + bd.booking_fee_paise
        + bd.minimum_topup_paise
        + bd.rounding_paise
        == bd.total_paise
    )
