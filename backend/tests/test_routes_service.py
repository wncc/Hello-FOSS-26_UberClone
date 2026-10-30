from unittest.mock import Mock

from backend.app.services.routes import RouteService
from matching import RouterEta, StraightLineEta
from routing import VehicleType


def test_without_router_uses_straight_line_eta():
    service = RouteService()

    assert service.has_roads is False
    assert isinstance(service.pickup_eta, StraightLineEta)


def test_with_router_uses_router_eta():
    router = Mock()
    router.services = {}

    service = RouteService(router)

    assert service.has_roads is True
    assert isinstance(service.pickup_eta, RouterEta)


def test_estimate_returns_none_for_unsupported_vehicle():
    router = Mock()
    router.services = {}

    service = RouteService(router)

    result = service.estimate(
        (19.0760, 72.8777),
        (19.0800, 72.8800),
        VehicleType.CAR,
    )

    assert result is None


def test_estimate_uses_road_router_result():
    router = Mock()
    router.services = {
        VehicleType.CAR: Mock(
            edges={
                "road-1": Mock(
                    geometry=[
                        (19.0760, 72.8777),
                        (19.0780, 72.8790),
                    ]
                )
            }
        )
    }
    router.route.return_value = Mock(
        segments=["road-1"],
        distance_m=350,
        eta_s=45,
    )

    service = RouteService(router)

    result = service.estimate(
        (19.0760, 72.8777),
        (19.0800, 72.8800),
        VehicleType.CAR,
    )

    assert result is not None
    assert result.distance_m == 350
    assert result.duration_s == 45
    assert result.geometry[0] == (19.0760, 72.8777)
    assert result.geometry[-1] == (19.0800, 72.8800)
    router.route.assert_called_once()