import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import DeathEvent, Server
from app.services.ingestion import ZipImporter


@pytest.mark.asyncio
async def test_kill_event_is_published_after_commit_and_not_duplicated(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'commit.db').as_posix()}"); sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection: await connection.run_sync(Base.metadata.create_all)
    server_id = uuid.uuid4(); line = f"2026.07.21-22.15.30;A;{'a'*32};B;{'b'*32};AR4;100;PC;PC;\n".encode()
    async with sessions() as session:
        session.add(Server(id=server_id, slug="commit", name="Commit")); await session.commit()
        async def assert_committed(**kwargs):
            assert await session.scalar(select(func.count()).select_from(DeathEvent)) == 1
            assert kwargs["event"] == "kill.created"
        publisher = AsyncMock(side_effect=assert_committed)
        monkeypatch.setattr("app.services.ingestion.event_service.publish_after_commit", publisher)
        importer = ZipImporter(session); path = "/deathlogs/world_0/day.csv"
        assert await importer.process_content(server_id, path, line, len(line), datetime.now(UTC)) == "processed"
        assert publisher.await_count == 1
        assert await importer.process_content(server_id, path, line, len(line), datetime.now(UTC)) == "skipped"
        assert publisher.await_count == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_rollback_or_invalid_file_never_publishes(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'rollback.db').as_posix()}"); sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection: await connection.run_sync(Base.metadata.create_all)
    server_id = uuid.uuid4(); publisher = AsyncMock(); monkeypatch.setattr("app.services.ingestion.event_service.publish_after_commit", publisher)
    async with sessions() as session:
        session.add(Server(id=server_id, slug="rollback", name="Rollback")); await session.commit()
        result = await ZipImporter(session).process_content(server_id, "/deathlogs/world_0/bad.csv", b"partial", 7, datetime.now(UTC))
        assert result == "failed" and publisher.await_count == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_identical_character_position_does_not_publish_position_twice(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'position.db').as_posix()}"); sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection: await connection.run_sync(Base.metadata.create_all)
    server_id = uuid.uuid4(); publisher = AsyncMock(); monkeypatch.setattr("app.services.ingestion.event_service.publish_after_commit", publisher)
    path = "/characters1-9/world_0/p1.sav"
    first = json.dumps({"BaseCharacter": {"Login": "A", "PosX": 10, "PosY": 20}}).encode()
    second = json.dumps({"BaseCharacter": {"Login": "B", "PosX": 10, "PosY": 20}}).encode()
    async with sessions() as session:
        session.add(Server(id=server_id, slug="position", name="Position")); await session.commit(); importer = ZipImporter(session)
        await importer.process_content(server_id, path, first, len(first), datetime.now(UTC))
        await importer.process_content(server_id, path, second, len(second), datetime.now(UTC))
        names = [call.kwargs["event"] for call in publisher.await_args_list]
        assert names.count("character.position.updated") == 1
        assert names == ["character.created", "character.position.updated", "character.updated"]
    await engine.dispose()
