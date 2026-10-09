"""Fan-out of backend events to connected frontend WebSockets.

A Starlette WebSocket cannot be written from two tasks at once. The broadcast
loop and the endpoint's initial snapshot both write to the same socket, so every
send goes through a PER-CONNECTION lock. Without it the two interleave, the
connection dies, the client reconnects, and you get a reconnect storm that looks
like a flaky network.
"""
from __future__ import annotations
import asyncio, json, logging
from typing import Any
from fastapi import WebSocket

log = logging.getLogger("hub")


class Hub:
    def __init__(self) -> None:
        self._clients: dict[WebSocket, asyncio.Lock] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients[ws] = asyncio.Lock()
        log.info("client connected (%d total)", len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.pop(ws, None)
        log.info("client disconnected (%d left)", len(self._clients))

    async def send(self, ws: WebSocket, type_: str, payload: Any) -> bool:
        """Send to one client, serialised against every other writer."""
        async with self._lock:
            lock = self._clients.get(ws)
        if lock is None:
            return False
        async with lock:
            try:
                await ws.send_text(json.dumps({"type": type_, "data": payload}))
                return True
            except Exception:
                return False

    async def broadcast(self, type_: str, payload: Any) -> None:
        msg = json.dumps({"type": type_, "data": payload})
        async with self._lock:
            targets = list(self._clients.items())
        dead = []
        for ws, lock in targets:
            async with lock:
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.pop(ws, None)

    @property
    def count(self) -> int:
        return len(self._clients)


hub = Hub()
