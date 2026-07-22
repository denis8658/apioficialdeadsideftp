import asyncio
import base64
import hashlib
import hmac
import json
import time
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import Server
from app.db.session import get_session
from app.main import app
from app.services.event_service import event_service


def token(role="SERVER_ADMIN", server_ids=("ws-test",), secret="route-secret"):
    encode = lambda value: base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=").decode()
    header = encode({"alg": "HS256"}); payload = encode({"sub": "u1", "role": role, "server_ids": list(server_ids), "exp": time.time() + 300})
    signature = base64.urlsafe_b64encode(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


@pytest.fixture
def websocket_app(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'ws.db').as_posix()}"); sessions = async_sessionmaker(engine, expire_on_commit=False)
    async def setup():
        async with engine.begin() as connection: await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session: session.add(Server(id=uuid.uuid4(), slug="ws-test", name="WS")); await session.commit()
    asyncio.run(setup())
    async def override():
        async with sessions() as session: yield session
    app.dependency_overrides[get_session] = override
    settings = get_settings(); previous = settings.websocket_jwt_secret; settings.websocket_jwt_secret = SecretStr("route-secret")
    monkeypatch.setattr(event_service, "latest_sequence", AsyncMock(return_value=5))
    monkeypatch.setattr(event_service, "replay", AsyncMock(return_value=[]))
    yield engine
    settings.websocket_jwt_secret = previous; app.dependency_overrides.clear(); asyncio.run(engine.dispose())


@pytest.mark.parametrize("channel,role", [("kills", "PUBLIC"), ("map", "MAP_VIEWER"), ("sync", "SERVER_ADMIN"), ("events", "MODERATOR")])
def test_all_websocket_channels_authenticate_and_send_connected(websocket_app, channel, role):
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/servers/ws-test/ws/{channel}?token={token(role=role)}", headers={"origin": "http://localhost:5173"}) as socket:
            connected = socket.receive_json()
            assert connected["event"] == "system.connected"
            assert connected["channel"] == channel and connected["sequence"] == 5
            socket.send_json({"event": "system.pong"})


@pytest.mark.parametrize("query,code", [("", 4401), ("?token=invalid", 4401), (f"?token={token(server_ids=('other',))}", 4403)])
def test_websocket_rejects_missing_invalid_or_unauthorized_token(websocket_app, query, code):
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(f"/api/v1/servers/ws-test/ws/kills{query}", headers={"origin": "http://localhost:5173"}):
                pass
        assert caught.value.code == code


def test_general_channel_subscribe_and_unsubscribe(websocket_app):
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/servers/ws-test/ws/events?token={token(role='MODERATOR')}", headers={"origin": "http://localhost:5173"}) as socket:
            socket.receive_json()
            socket.send_json({"action": "subscribe", "events": ["kill.created"], "filters": {"player_id": "p1", "unsafe": "ignored"}})
            update = socket.receive_json()
            assert update == {"event": "system.subscription.updated", "events": ["kill.created"], "filters": {"player_id": "p1"}}
            socket.send_json({"action": "unsubscribe", "events": ["kill.created"]})
            assert socket.receive_json()["events"] == []


def test_reconnect_replays_or_requests_resync(websocket_app, monkeypatch):
    replayed = {"event_id": str(uuid.uuid4()), "event": "kill.created", "server_id": "x", "sequence": 5, "occurred_at": "2026-07-21T00:00:00Z", "published_at": "2026-07-21T00:00:01Z", "data": {}}
    monkeypatch.setattr(event_service, "replay", AsyncMock(return_value=[replayed]))
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/servers/ws-test/ws/kills?token={token(role='PUBLIC')}&after_sequence=4", headers={"origin": "http://localhost:5173"}) as socket:
            socket.receive_json(); assert socket.receive_json()["event"] == "kill.created"
    monkeypatch.setattr(event_service, "replay", AsyncMock(return_value=None))
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/servers/ws-test/ws/kills?token={token(role='PUBLIC')}&after_sequence=4", headers={"origin": "http://localhost:5173"}) as socket:
            socket.receive_json(); assert socket.receive_json()["event"] == "system.resync_required"


def test_websocket_rejects_unlisted_or_missing_origin_before_auth(websocket_app):
    with TestClient(app) as client:
        for headers in ({"origin": "https://evil.example"}, {}):
            with pytest.raises(WebSocketDisconnect) as caught:
                with client.websocket_connect(
                    f"/api/v1/servers/ws-test/ws/kills?token={token(role='PUBLIC')}",
                    headers=headers,
                ):
                    pass
            assert caught.value.code == 4403


def test_websocket_normalizes_allowed_origin_trailing_slash(websocket_app):
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/servers/ws-test/ws/kills?token={token(role='PUBLIC')}",
            headers={"origin": "http://localhost:5173/"},
        ) as socket:
            assert socket.receive_json()["event"] == "system.connected"
