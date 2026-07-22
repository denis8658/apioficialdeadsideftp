import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

from app.core.config import get_settings
from app.websocket.subscriptions import sanitize_filters, subscription_matches

logger = logging.getLogger(__name__)


@dataclass(eq=False)
class WebSocketConnection:
    websocket: WebSocket
    server_id: str
    channel: str
    user_id: str
    connection_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    subscriptions: set[str] | None = None
    filters: dict[str, str] = field(default_factory=dict)
    last_pong_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ConnectionLimitError(RuntimeError):
    pass


class ConnectionManager:
    def __init__(self):
        self.settings = get_settings()
        self._connections: dict[str, dict[str, set[WebSocketConnection]]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, server_id: str, channel: str, user_id: str) -> WebSocketConnection:
        async with self._lock:
            server_connections = sum(len(items) for items in self._connections.get(server_id, {}).values())
            user_connections = sum(1 for channels in self._connections.values() for items in channels.values() for item in items if item.user_id == user_id)
            if server_connections >= self.settings.websocket_max_connections_per_server:
                raise ConnectionLimitError("server connection limit reached")
            if user_connections >= self.settings.websocket_max_connections_per_user:
                raise ConnectionLimitError("user connection limit reached")
            await websocket.accept()
            connection = WebSocketConnection(websocket, server_id, channel, user_id)
            self._connections.setdefault(server_id, {}).setdefault(channel, set()).add(connection)
            return connection

    async def disconnect(self, connection: WebSocketConnection, close_code: int | None = None):
        async with self._lock:
            channels = self._connections.get(connection.server_id, {})
            channels.get(connection.channel, set()).discard(connection)
            if connection.channel in channels and not channels[connection.channel]:
                channels.pop(connection.channel, None)
            if not channels:
                self._connections.pop(connection.server_id, None)
        if close_code is not None:
            try:
                await connection.websocket.close(code=close_code)
            except Exception:
                pass

    async def broadcast_to_channel(self, server_id: str, channel: str, event: dict[str, Any]) -> int:
        async with self._lock:
            connections = list(self._connections.get(server_id, {}).get(channel, set()))
        if channel == "events":
            connections = [item for item in connections if subscription_matches(event, item.subscriptions, item.filters)]
        results = await asyncio.gather(*(self._send(item, event) for item in connections), return_exceptions=True)
        return sum(result is True for result in results)

    async def broadcast_to_server(self, server_id: str, event: dict[str, Any]) -> int:
        async with self._lock:
            channels = list(self._connections.get(server_id, {}))
        return sum([await self.broadcast_to_channel(server_id, channel, event) for channel in channels])

    async def send_personal(self, connection: WebSocketConnection, event: dict[str, Any]) -> bool:
        return await self._send(connection, event)

    async def _send(self, connection: WebSocketConnection, event: dict[str, Any]) -> bool:
        try:
            await asyncio.wait_for(connection.websocket.send_json(event), timeout=self.settings.websocket_send_timeout_seconds)
            return True
        except Exception:
            logger.warning("WebSocket send failed", extra={"server_id": connection.server_id, "channel": connection.channel})
            await self.disconnect(connection, 1011)
            return False

    async def subscribe(self, connection: WebSocketConnection, events: list[str], filters: dict[str, Any]):
        if connection.subscriptions is None:
            connection.subscriptions = set()
        connection.subscriptions.update(str(event) for event in events)
        connection.filters = sanitize_filters(filters)

    async def unsubscribe(self, connection: WebSocketConnection, events: list[str]):
        if connection.subscriptions is None:
            connection.subscriptions = set()
        connection.subscriptions.difference_update(str(event) for event in events)

    def connection_count(self, server_id: str | None = None, channel: str | None = None) -> int:
        source = {server_id: self._connections.get(server_id, {})} if server_id else self._connections
        return sum(len(items) for channels in source.values() for name, items in channels.items() if channel is None or name == channel)

    def status(self, server_id: str) -> dict[str, int]:
        channels = self._connections.get(server_id, {})
        values = {name: len(channels.get(name, set())) for name in ("kills", "map", "sync", "events")}
        return {"total": sum(values.values()), **values}

    async def close_server_connections(self, server_id: str, code: int = 1000):
        async with self._lock:
            connections = [item for items in self._connections.get(server_id, {}).values() for item in items]
        await asyncio.gather(*(self.disconnect(item, code) for item in connections), return_exceptions=True)

    async def close_all(self):
        async with self._lock:
            connections = [item for channels in self._connections.values() for items in channels.values() for item in items]
        await asyncio.gather(*(self.disconnect(item, 1000) for item in connections), return_exceptions=True)

    async def snapshot(self) -> list[WebSocketConnection]:
        async with self._lock:
            return [item for channels in self._connections.values() for items in channels.values() for item in items]


connection_manager = ConnectionManager()
