import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.websocket.heartbeat import HeartbeatService
from app.websocket.manager import ConnectionLimitError, ConnectionManager


class FakeWebSocket:
    def __init__(self, delay=0, fail=False):
        self.accepted = False; self.sent = []; self.closed = None; self.delay = delay; self.fail = fail
    async def accept(self): self.accepted = True
    async def send_json(self, value):
        if self.delay: await asyncio.sleep(self.delay)
        if self.fail: raise RuntimeError("send failed")
        self.sent.append(value)
    async def close(self, code=1000): self.closed = code


@pytest.mark.asyncio
async def test_multiple_clients_receive_only_the_correct_channel():
    manager = ConnectionManager(); kills_a = FakeWebSocket(); kills_b = FakeWebSocket(); map_socket = FakeWebSocket()
    await manager.connect(kills_a, "s", "kills", "a"); await manager.connect(kills_b, "s", "kills", "b"); await manager.connect(map_socket, "s", "map", "c")
    sent = await manager.broadcast_to_channel("s", "kills", {"event": "kill.created", "data": {}})
    assert sent == 2 and len(kills_a.sent) == len(kills_b.sent) == 1 and map_socket.sent == []


@pytest.mark.asyncio
async def test_subscribe_filters_and_unsubscribe():
    manager = ConnectionManager(); socket = FakeWebSocket(); connection = await manager.connect(socket, "s", "events", "u")
    await manager.subscribe(connection, ["kill.created"], {"player_id": "p1"})
    matching = {"event": "kill.created", "data": {"killer": {"id": "p1"}}}
    ignored = {"event": "vehicle.position.updated", "data": {"player_id": "p1"}}
    assert await manager.broadcast_to_channel("s", "events", matching) == 1
    assert await manager.broadcast_to_channel("s", "events", ignored) == 0
    await manager.unsubscribe(connection, ["kill.created"])
    assert await manager.broadcast_to_channel("s", "events", ignored) == 0


@pytest.mark.asyncio
async def test_slow_or_failed_client_does_not_block_healthy_client(monkeypatch):
    manager = ConnectionManager(); monkeypatch.setattr(manager.settings, "websocket_send_timeout_seconds", 0.01)
    slow = FakeWebSocket(delay=0.1); healthy = FakeWebSocket()
    await manager.connect(slow, "s", "kills", "slow"); await manager.connect(healthy, "s", "kills", "healthy")
    assert await manager.broadcast_to_channel("s", "kills", {"event": "kill.created"}) == 1
    assert healthy.sent and slow.closed == 1011


@pytest.mark.asyncio
async def test_connection_limits_per_server_and_user(monkeypatch):
    manager = ConnectionManager(); monkeypatch.setattr(manager.settings, "websocket_max_connections_per_server", 1)
    await manager.connect(FakeWebSocket(), "s", "kills", "u")
    with pytest.raises(ConnectionLimitError): await manager.connect(FakeWebSocket(), "s", "kills", "other")
    manager = ConnectionManager(); monkeypatch.setattr(manager.settings, "websocket_max_connections_per_server", 10); monkeypatch.setattr(manager.settings, "websocket_max_connections_per_user", 1)
    await manager.connect(FakeWebSocket(), "s", "kills", "u")
    with pytest.raises(ConnectionLimitError): await manager.connect(FakeWebSocket(), "other", "kills", "u")


@pytest.mark.asyncio
async def test_heartbeat_removes_dead_connection(monkeypatch):
    manager = ConnectionManager(); socket = FakeWebSocket(); connection = await manager.connect(socket, "s", "kills", "u")
    heartbeat = HeartbeatService(manager); monkeypatch.setattr(heartbeat.settings, "websocket_heartbeat_timeout_seconds", 1)
    connection.last_pong_at = datetime.now(UTC) - timedelta(seconds=2)
    await heartbeat.tick()
    assert socket.closed == 1008 and manager.connection_count() == 0
