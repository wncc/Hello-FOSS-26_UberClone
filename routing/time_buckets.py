"""Time-of-week buckets: (weekday | saturday | sunday) x hour of day = 72 buckets.

Coarser than the 7 x 288 five-minute grid used by commercial traffic products on
purpose: with little data, 72 buckets fill up ~28x faster. Weekdays share one
profile; split them later once each weekday has enough samples on its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo

WEEKDAY, SATURDAY, SUNDAY = 0, 1, 2
HOURS = 24
BUCKET_COUNT = 3 * HOURS

IST = timezone(timedelta(hours=5, minutes=30), "IST")


@dataclass(frozen=True)
class TimeBuckets:
    tz: tzinfo  # the city's local time zone; traffic follows local clocks, not UTC

    def local(self, when: datetime) -> datetime:
        if when.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return when.astimezone(self.tz)

    def of(self, when: datetime) -> int:
        local = self.local(when)
        wd = local.weekday()
        daytype = WEEKDAY if wd < 5 else SATURDAY if wd == 5 else SUNDAY
        return daytype * HOURS + local.hour

    def local_date(self, when: datetime) -> date:
        return self.local(when).date()


def daytype_of(bucket: int) -> int:
    return bucket // HOURS


def hour_of(bucket: int) -> int:
    return bucket % HOURS
