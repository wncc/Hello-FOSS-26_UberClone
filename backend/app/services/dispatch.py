"""Dispatch: runs the matching engine against the database every few seconds.

Each cycle:
  1. builds the engine's /state payload from searching rides, online drivers and live offers
  2. calls matching.run_cycle (broadcast pings, nearest acceptor wins, timeouts, ...)
  3. turns the engine's decisions into offer / ride updates and WebSocket events
     (exactly the diff-and-emit glue the original engine's README asked the backend for)
  4. gives up on rides that searched longer than search_timeout_seconds
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from matching import MatchingConfig, run_cycle

from ..context import AppContext
from ..models import (
    DRIVER_BUSY_STATUSES, DriverProfile, DriverStatus, OfferStatus, Ride, RideOffer, RideStatus, User,
)
from .rides import ride_summary

log = logging.getLogger(__name__)
LIVE = (OfferStatus.PINGED, OfferStatus.ACCEPTED)


def _ms(t: datetime) -> int:
    return int(t.timestamp() * 1000)


class Dispatcher:
    def __init__(self, ctx: AppContext, rng: random.Random | None = None):
        self.ctx = ctx
        self.rng = rng or random.Random()
        self.config = MatchingConfig(ping_timeout_s=ctx.settings.ping_timeout_seconds)
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    # -- loop --------------------------------------------------------------- #

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # keep dispatching; one bad cycle must not stop matching
                log.exception("dispatch cycle failed")
            await asyncio.sleep(self.ctx.settings.matching_tick_seconds)

    async def tick(self, now: datetime | None = None) -> dict[str, int]:
        async with self._lock:   # cycles never overlap
            async with self.ctx.db.sessions() as session:
                events: list[tuple[str, str, dict]] = []
                stats = await self._cycle(session, now or datetime.now(timezone.utc), events)
                await session.commit()
            await self.ctx.hub.send_many(events)
            return stats

    # -- one cycle ---------------------------------------------------------- #

    async def _cycle(self, session: AsyncSession, now: datetime, events: list) -> dict[str, int]:
        s = self.ctx.settings
        searching = list(await session.scalars(select(Ride).where(Ride.status == RideStatus.SEARCHING)))
        gave_up = await self._give_up_stale(session, searching, now, events)
        rides = {r.id: r for r in searching if r.status is RideStatus.SEARCHING}
        offers = list(await session.scalars(select(RideOffer).where(
            RideOffer.ride_id.in_(rides), RideOffer.status.in_(LIVE)))) if rides else []
        # A ping left unanswered counts as a rejection of that ride, so the driver isn't re-pinged for it.
        for o in offers:
            if o.status is OfferStatus.PINGED and (now - o.created_at).total_seconds() > s.ping_timeout_seconds:
                o.status = OfferStatus.EXPIRED
                events.append((o.driver_id, "ride:ping_cancelled", {"ride_id": o.ride_id, "reason": "timeout"}))
        offers = [o for o in offers if o.status in LIVE]
        refused = set() if not rides else {
            (o.ride_id, o.driver_id) for o in await session.scalars(select(RideOffer).where(
                RideOffer.ride_id.in_(rides), RideOffer.status.in_((OfferStatus.REJECTED, OfferStatus.EXPIRED))))}

        busy = set(await session.scalars(select(Ride.driver_id).where(Ride.status.in_(DRIVER_BUSY_STATUSES))))
        fresh_after = now - timedelta(seconds=s.location_stale_seconds)
        profiles = {p.user_id: p for p in await session.scalars(select(DriverProfile).where(
            DriverProfile.is_online.is_(True), DriverProfile.status == DriverStatus.APPROVED,
            DriverProfile.location_at >= fresh_after)) if p.user_id not in busy}

        offer_by_driver: dict[str, RideOffer] = {}
        for o in sorted(offers, key=lambda o: o.created_at):
            if o.driver_id in offer_by_driver:              # at most one live offer per driver
                offer_by_driver[o.driver_id].status = OfferStatus.EXPIRED
            offer_by_driver[o.driver_id] = o

        drivers_state = []
        for p in profiles.values():
            rec = {"id": p.user_id, "lat": p.lat, "lng": p.lng, "vehicle": p.vehicle_type,
                   "status": "free", "riderId": None, "pingedAt": None}
            o = offer_by_driver.get(p.user_id)
            if o:
                rec.update(status="pinged" if o.status is OfferStatus.PINGED else "accepted",
                           riderId=o.ride_id, pingedAt=_ms(o.created_at))
            drivers_state.append(rec)

        riders_state = []
        for r in rides.values():
            pinged = [o.driver_id for o in offer_by_driver.values()
                      if o.ride_id == r.id and o.driver_id in profiles]
            riders_state.append({
                "id": r.id, "lat": r.pickup_lat, "lng": r.pickup_lng, "vehicle": r.vehicle_type,
                "status": "driver_pinged" if pinged else "ping_pending", "driverId": None, "driverIds": pinged,
                "excludedDriverIds": [d for (ride_id, d) in refused if ride_id == r.id],
            })

        result = run_cycle({"drivers": drivers_state, "riders": riders_state}, now,
                           self.ctx.routes.pickup_eta, self.config, self.rng)
        new_driver = {d["id"]: d for d in result.state["drivers"]}

        # Offers for drivers who dropped out (went offline, stale GPS, got busy) die.
        for driver_id, o in offer_by_driver.items():
            if driver_id not in profiles:
                o.status = OfferStatus.EXPIRED
                events.append((driver_id, "ride:ping_cancelled", {"ride_id": o.ride_id}))

        # Matches.
        for r in result.state["riders"]:
            if r["status"] != "accepted":
                continue
            ride, winner = rides[r["id"]], r["driverId"]
            ride.status, ride.driver_id, ride.assigned_at = RideStatus.DRIVER_ASSIGNED, winner, now
            for o in offers:
                if o.ride_id != ride.id or o.status not in LIVE:
                    continue
                if o.driver_id == winner:
                    o.status = OfferStatus.WON
                else:
                    o.status = OfferStatus.LOST if o.status is OfferStatus.ACCEPTED else OfferStatus.RELEASED
                    events.append((o.driver_id, "ride:taken", {"ride_id": ride.id}))
            driver = await session.get(User, winner)
            profile = profiles[winner]
            events.append((ride.rider_id, "ride:driver_assigned", {
                **ride_summary(ride), "driver": {"id": winner, "name": driver.name, "rating": driver.rating,
                                                  "vehicle_number": profile.vehicle_number,
                                                  "vehicle_model": profile.vehicle_model,
                                                  "lat": profile.lat, "lng": profile.lng}}))
            events.append((winner, "ride:confirmed", ride_summary(ride)))

        # New pings and pings the engine took back (timeout / released).
        for driver_id, d in new_driver.items():
            old = offer_by_driver.get(driver_id)
            if old and old.status in LIVE and d["status"] == "free":
                old.status = OfferStatus.EXPIRED if old.status is OfferStatus.PINGED else OfferStatus.RELEASED
                events.append((driver_id, "ride:ping_cancelled", {"ride_id": old.ride_id}))
            repinged = old is not None and old.status in LIVE and d["pingedAt"] != _ms(old.created_at)
            if repinged:
                old.status = OfferStatus.EXPIRED
            if d["status"] == "pinged" and (old is None or old.ride_id != d["riderId"] or old.status not in LIVE):
                ride = rides[d["riderId"]]
                session.add(RideOffer(ride_id=ride.id, driver_id=driver_id, created_at=now))
                events.append((driver_id, "ride:ping", {**ride_summary(ride),
                                                        "expires_in_s": self.config.ping_timeout_s}))

        return {**result.stats, "no_drivers": gave_up}

    async def _give_up_stale(self, session: AsyncSession, rides: list[Ride], now: datetime, events: list) -> int:
        """Rides nobody took within search_timeout_seconds become no_drivers."""
        stale = [r for r in rides
                 if (now - r.searching_since).total_seconds() > self.ctx.settings.search_timeout_seconds]
        if not stale:
            return 0
        for o in await session.scalars(select(RideOffer).where(
                RideOffer.ride_id.in_([r.id for r in stale]), RideOffer.status.in_(LIVE))):
            o.status = OfferStatus.RELEASED
            events.append((o.driver_id, "ride:ping_cancelled", {"ride_id": o.ride_id}))
        for ride in stale:
            ride.status = RideStatus.NO_DRIVERS
            events.append((ride.rider_id, "ride:no_drivers", ride_summary(ride)))
        return len(stale)
