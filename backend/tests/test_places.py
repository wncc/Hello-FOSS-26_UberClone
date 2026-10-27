
import asyncio

from backend.app.services.place_search import PlaceResult, PlaceSearchService


class FakePlaceProvider:
    def __init__(self):
        self.calls = []

    async def search(self, query, near=None):
        self.calls.append((query, near))
        return [
            PlaceResult(
                name="Dadar Station",
                address="Dadar, Mumbai",
                lat=19.0176,
                lng=72.8562,
            )
        ]


def test_place_search_service_returns_provider_results():
    async def run_test():
        provider = FakePlaceProvider()
        service = PlaceSearchService(provider)

        results = await service.search(
            "Dadar station",
            (19.0176, 72.8562),
        )

        assert len(results) == 1
        assert results[0].name == "Dadar Station"
        assert results[0].address == "Dadar, Mumbai"
        assert provider.calls == [
            ("Dadar station", (19.0176, 72.8562))
        ]

    asyncio.run(run_test())


def test_place_search_service_caches_repeated_queries():
    async def run_test():
        provider = FakePlaceProvider()
        service = PlaceSearchService(provider)

        first = await service.search("Dadar station")
        second = await service.search("Dadar station")

        assert first == second
        assert len(provider.calls) == 1

    asyncio.run(run_test())
