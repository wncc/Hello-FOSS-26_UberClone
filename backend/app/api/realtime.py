"""WebSocket: /ws?token=<access token>.

Server -> client: {"event": "...", "data": {...}}
  ride:ping, ride:ping_cancelled, ride:confirmed, ride:taken, ride:driver_assigned,
  ride:driver_arrived, ride:started, ride:completed, ride:cancelled, ride:driver_cancelled,
  ride:no_drivers, driver:location
Client -> server (drivers): {"type": "location", "lat": .., "lng": .., "heading": .., "speed_kmh": ..}
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ..errors import DomainError
from ..models import DriverProfile, Role, User
from ..schemas import LocationIn
from ..deps import user_from_token
from ..services.locations import update_location

router = APIRouter()


@router.websocket("/ws")
async def websocket(ws: WebSocket, token: str) -> None:
    ctx = ws.app.state.ctx
    async with ctx.db.sessions() as session:
        try:
            user = await user_from_token(token, ctx, session)
        except HTTPException:
            await ws.close(code=4401)
            return
        user_id, role = user.id, user.role

    await ctx.hub.connect(user_id, ws)
    try:
        while True:
            message = await ws.receive_json()
            if message.get("type") == "location" and role is Role.DRIVER:
                await _location(ws, ctx, user_id, message)
            elif message.get("type") == "ping":
                await ws.send_json({"event": "pong", "data": {}})
    except WebSocketDisconnect:
        pass
    finally:
        ctx.hub.disconnect(user_id, ws)


async def _location(ws: WebSocket, ctx, user_id: str, message: dict) -> None:
    try:
        loc = LocationIn(**{k: v for k, v in message.items() if k != "type"})
    except ValidationError:
        await ws.send_json({"event": "error", "data": {"message": "invalid location"}})
        return
    async with ctx.db.sessions() as session:
        user = await session.get(User, user_id)
        profile = await session.get(DriverProfile, user_id)
        if profile is None:
            await ws.send_json({"event": "error", "data": {"message": "no driver profile"}})
            return
        try:
            await update_location(session, ctx, user, profile, loc)
        except DomainError as e:
            await ws.send_json({"event": "error", "data": {"message": e.message}})
