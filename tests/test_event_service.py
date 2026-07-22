import importlib
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import DomainEvent, Server
from app.services.event_service import EventService


@pytest.mark.asyncio
async def test_sequences_are_increasing_isolated_and_replayable(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'events.db').as_posix()}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection: await connection.run_sync(Base.metadata.create_all)
    first_server, second_server = uuid.uuid4(), uuid.uuid4()
    async with sessions() as session:
        session.add_all([Server(id=first_server, slug="event-a", name="A"), Server(id=second_server, slug="event-b", name="B")]); await session.commit()
    module = importlib.import_module("app.services.event_service")
    monkeypatch.setattr(module, "SessionLocal", sessions)
    broadcast = AsyncMock(return_value=1)
    monkeypatch.setattr(module.connection_manager, "broadcast_to_channel", broadcast)
    service = EventService()
    one = await service.publish_after_commit(event="kill.created", server_id=first_server, entity_type="kill", entity_id="1", data={"x": 1})
    two = await service.publish_after_commit(event="death.created", server_id=first_server, entity_type="death", entity_id="2", data={"x": 2})
    other = await service.publish_after_commit(event="sync.started", server_id=second_server, data={})
    assert [one["sequence"], two["sequence"], other["sequence"]] == [1, 2, 1]
    assert [event["sequence"] for event in await service.replay(first_server, 0)] == [1, 2]
    assert (await service.replay(first_server, 1))[0]["event"] == "death.created"
    await engine.dispose()


@pytest.mark.asyncio
async def test_broadcast_failure_does_not_remove_persisted_event(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'failure.db').as_posix()}"); sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection: await connection.run_sync(Base.metadata.create_all)
    server_id = uuid.uuid4()
    async with sessions() as session: session.add(Server(id=server_id, slug="failure", name="Failure")); await session.commit()
    module = importlib.import_module("app.services.event_service"); monkeypatch.setattr(module, "SessionLocal", sessions)
    monkeypatch.setattr(module.connection_manager, "broadcast_to_channel", AsyncMock(side_effect=RuntimeError("socket down")))
    service = EventService(); result = await service.publish_after_commit(event="kill.created", server_id=server_id, data={})
    assert result is not None
    async with sessions() as session: assert await session.scalar(select(func.count()).select_from(DomainEvent)) == 1
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("event_name,expected_channels", [
    ("kill.created", {"kills", "events"}), ("death.created", {"kills", "events"}),
    ("character.position.updated", {"map", "events"}), ("vehicle.position.updated", {"map", "events"}),
    ("vehicle.disappeared", {"map", "events"}), ("sync.started", {"sync", "events"}),
    ("sync.completed", {"sync", "events"}), ("sync.failed", {"sync", "events"}),
    ("ftp.connected", {"sync", "events"}), ("ftp.disconnected", {"sync", "events"}),
])
async def test_event_channel_mapping(event_name, expected_channels, monkeypatch):
    module = importlib.import_module("app.services.event_service"); calls = []
    async def record(server, channel, payload): calls.append(channel); return 1
    monkeypatch.setattr(module.connection_manager, "broadcast_to_channel", record)
    await EventService()._broadcast({"event": event_name, "server_id": "s", "data": {}})
    assert set(calls) == expected_channels
