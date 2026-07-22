import json
import zipfile

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import CharacterCurrent, RemoteFile
from app.services.ingestion import ZipImporter


@pytest.mark.asyncio
async def test_invalid_file_never_overwrites_valid_current_state(tmp_path):
    database = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database.as_posix()}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    archive = tmp_path / "sample.zip"
    source_path = "prefix/characters1-9/world_0/42.sav"
    valid = {"BaseCharacter": {"Login": "Valid", "PosX": 10, "PosY": 20}}
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr(source_path, json.dumps(valid))
    async with sessions() as session:
        await ZipImporter(session).import_archive(archive, "test-server")

    with zipfile.ZipFile(archive, "w") as target:
        target.writestr(source_path, b'{"BaseCharacter": {')
    async with sessions() as session:
        result = await ZipImporter(session).import_archive(archive, "test-server")
        current = await session.scalar(select(CharacterCurrent).where(CharacterCurrent.player_id == "42"))
        remote = await session.scalar(select(RemoteFile).where(RemoteFile.remote_path == source_path))
        assert result["failed"] == 1
        assert current.login == "Valid"
        assert current.pos_x == 10
        assert remote.status == "error"
        assert remote.processing_error

    await engine.dispose()
