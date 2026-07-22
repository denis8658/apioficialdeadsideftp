import asyncio
import base64
import hashlib
import hmac
import importlib
import json
import time
import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import DomainEvent, Server, ServerEventSequence
from app.db.session import get_session
from app.main import app
from app.services.ingestion import ZipImporter


def jwt(secret="integration-secret"):
    enc = lambda value: base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=").decode()
    header = enc({"alg": "HS256"}); payload = enc({"sub": "admin", "role": "SUPER_ADMIN", "server_ids": [], "exp": time.time() + 300})
    signature = base64.urlsafe_b64encode(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


def test_deathlog_commit_reaches_websocket_once(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'integrated.db').as_posix()}"); sessions = async_sessionmaker(engine, expire_on_commit=False); server_id = uuid.uuid4()
    async def setup():
        async with engine.begin() as connection: await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session: session.add(Server(id=server_id, slug="integrated", name="Integrated")); await session.commit()
    asyncio.run(setup())
    async def override():
        async with sessions() as session: yield session
    app.dependency_overrides[get_session] = override
    event_module = importlib.import_module("app.services.event_service"); monkeypatch.setattr(event_module, "SessionLocal", sessions)
    settings = get_settings(); previous = settings.websocket_jwt_secret; settings.websocket_jwt_secret = SecretStr("integration-secret")
    line = f"2026.07.21-22.15.30;A;{'a'*32};B;{'b'*32};AR4;100;PC;PC;\n".encode(); path = "/deathlogs/world_0/day.csv"
    async def ingest():
        async with sessions() as session: return await ZipImporter(session).process_content(server_id, path, line, len(line), datetime.now(UTC))
    async def counts():
        async with sessions() as session:
            return await session.scalar(select(func.count()).select_from(DomainEvent)), await session.scalar(select(ServerEventSequence.value).where(ServerEventSequence.server_id == server_id))
    try:
        with TestClient(app) as client:
            with client.websocket_connect(f"/api/v1/servers/integrated/ws/kills?token={jwt()}", headers={"origin": "http://localhost:5173"}) as socket:
                assert socket.receive_json()["event"] == "system.connected"
                assert client.portal.call(ingest) == "processed"
                event = socket.receive_json()
                assert event["event"] == "kill.created" and event["data"]["weapon"] == "AR4"
                assert client.portal.call(ingest) == "skipped"
                assert client.portal.call(counts) == (1, 1)
    finally:
        settings.websocket_jwt_secret = previous; app.dependency_overrides.clear(); asyncio.run(engine.dispose())
