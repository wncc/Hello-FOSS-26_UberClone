from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request

from ..services.place_search import PlaceResult

router = APIRouter(prefix="/places", tags=["places"])
log = logging.getLogger(__name__)


@router.get("/search", response_model=list[PlaceResult])
async def search_places(
    request: Request,
    q: str = Query(min_length=1, max_length=120),
    near: str | None = None,
) -> list[PlaceResult]:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Enter a place to search for.")

    location = None
    if near is not None:
        try:
            lat_text, lng_text = near.split(",")
            lat, lng = float(lat_text), float(lng_text)
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                raise ValueError
            location = (lat, lng)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="near must be latitude,longitude.",
            ) from None

    try:
        return await request.app.state.place_search.search(query, location)
    except Exception:
        log.exception("Place search provider failed")
        raise HTTPException(
            status_code=503,
            detail="Place search is temporarily unavailable. You can still move the map pin.",
        ) from None