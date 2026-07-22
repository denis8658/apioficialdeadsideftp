import asyncio
from datetime import UTC, datetime

from app.core.config import get_settings
from app.websocket.manager import ConnectionManager


class HeartbeatService:
    def __init__(self, manager: ConnectionManager):
        self.manager = manager
        self.settings = get_settings()
        self._task: asyncio.Task | None = None

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="websocket-heartbeat")

    async def stop(self):
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def tick(self):
        now = datetime.now(UTC)
        for connection in await self.manager.snapshot():
            if (now - connection.last_pong_at).total_seconds() > self.settings.websocket_heartbeat_timeout_seconds:
                await self.manager.disconnect(connection, 1008)
            else:
                await self.manager.send_personal(connection, {"event": "system.ping", "published_at": now.isoformat()})

    async def _run(self):
        try:
            while True:
                await asyncio.sleep(self.settings.websocket_heartbeat_interval_seconds)
                await self.tick()
        except asyncio.CancelledError:
            raise
