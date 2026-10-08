"""WebSocket hub: pushes events to every open connection of a user.

Single-process for now; with several API instances, publish through Redis pub/sub
(phase 6) so an event reaches a user connected to another instance.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)


class Hub:
    def __init__(self) -> None:
        self._sockets: dict[str, set[WebSocket]] = defaultdict(set)
        self.sent: list[tuple[str, dict]] = []   # recent events, for tests and debugging
        self.keep_sent = 1000

    async def connect(self, user_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._sockets[user_id].add(ws)

    def disconnect(self, user_id: str, ws: WebSocket) -> None:
        self._sockets[user_id].discard(ws)
        if not self._sockets[user_id]:
            self._sockets.pop(user_id, None)

    def is_connected(self, user_id: str) -> bool:
        return bool(self._sockets.get(user_id))

    async def send(self, user_id: str, event: str, data: dict[str, Any]) -> None:
        message = {"event": event, "data": data}
        self.sent.append((user_id, message))
        del self.sent[:-self.keep_sent]
        for ws in list(self._sockets.get(user_id, ())):
            try:
                await ws.send_json(message)
            except Exception:  # client went away mid-send
                log.debug("dropping dead socket for %s", user_id)
                self.disconnect(user_id, ws)

    async def send_many(self, events: list[tuple[str, str, dict[str, Any]]]) -> None:
        await asyncio.gather(*(self.send(u, e, d) for u, e, d in events))

    def events_for(self, user_id: str, event: str | None = None) -> list[dict]:
        return [m for u, m in self.sent if u == user_id and (event is None or m["event"] == event)]
