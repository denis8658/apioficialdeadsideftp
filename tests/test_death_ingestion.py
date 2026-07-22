import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import DeathEvent, Server
from app.services.ingestion import ZipImporter


@pytest.mark.asyncio
async def test_repeated_and_rotated_deathlog_events_are_deduplicated(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'deaths.db').as_posix()}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    server_id = uuid.uuid4()
    line = f"2026.07.21-22.15.30;A;{'a'*32};B;{'b'*32};AR4;100;PC;PC;\n".encode()
    async with sessions() as session:
        session.add(Server(id=server_id, slug="combat-test", name="Combat test")); await session.commit()
        importer = ZipImporter(session)
        first = "/Deadside/Saved/actual1/deathlogs/world_0/first.csv"
        rotated = "/Deadside/Saved/actual1/deathlogs/world_0/rotated.csv"
        assert await importer.process_content(server_id, first, line, len(line), datetime.now(UTC)) == "processed"
        assert await importer.process_content(server_id, first, line, len(line), datetime.now(UTC)) == "skipped"
        assert await importer.process_content(server_id, rotated, line, len(line), datetime.now(UTC)) == "processed"
        assert await session.scalar(select(func.count()).select_from(DeathEvent)) == 1
        death = await session.scalar(select(DeathEvent))
        assert death.source_line == 1
        assert death.is_player_kill is True
    await engine.dispose()
