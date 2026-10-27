"""Driver earnings: completed rides, grouped by calendar day in India time."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from routing import IST

from ..models import Ride, RideStatus
from ..schemas import EarningsDayOut, EarningsOut


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def driver_earnings(session: AsyncSession, driver_id: str, days: int) -> EarningsOut:
    """The last `days` IST calendar days, today included, with a row for every day (0 when idle).

    Days are counted in IST, not UTC: a ride finished at 00:30 in Mumbai belongs to that day,
    even though it's still the previous evening in UTC.
    """
    today = _now().astimezone(IST).date()
    first = today - timedelta(days=days - 1)
    start = datetime.combine(first, time.min, tzinfo=IST)      # midnight IST; stored as UTC
    per_day = {first + timedelta(days=i): EarningsDayOut(day=first + timedelta(days=i), earnings_paise=0, trips=0)
               for i in range(days)}

    rides = await session.scalars(select(Ride).where(
        Ride.driver_id == driver_id, Ride.status == RideStatus.COMPLETED, Ride.completed_at >= start))
    for ride in rides:
        bucket = per_day.get(ride.completed_at.astimezone(IST).date())
        if bucket is None:                                        # a clock ahead of ours; not a real day yet
            continue
        bucket.earnings_paise += ride.fare_final_paise or 0
        bucket.trips += 1

    rows = list(per_day.values())
    return EarningsOut(days=days, total_paise=sum(r.earnings_paise for r in rows),
                       trips=sum(r.trips for r in rows), per_day=rows)
