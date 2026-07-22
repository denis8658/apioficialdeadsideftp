import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import CharacterPermanentData, Server, StorageCurrent, StorageSnapshot
from app.services.ingestion import ZipImporter


@pytest.mark.asyncio
async def test_json_storage_and_permanent_character_are_persisted_idempotently(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'json.db').as_posix()}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    server_id = uuid.uuid4()
    modified = datetime.now(UTC)
    storage_path = "Deadside/Saved/actual1/storages1-9/world_0/42_itemstorage_world_0_X08_Y07_ItemStorage01_2.sav"
    storage = json.dumps({"Inventory": {"Item0": {"Index": 5, "Count": 2}}}).encode()
    permanent_path = "Deadside/Saved/actual1/characters_nowipe/42.sav"
    permanent = json.dumps({"BaseCharacter": {"Login": "P"}, "Character": {"Achievements": {"Count": 0}}}).encode()
    async with sessions() as session:
        session.add(Server(id=server_id, slug="json-test", name="JSON test"))
        await session.commit()
        importer = ZipImporter(session)
        assert await importer.process_content(server_id, storage_path, storage, len(storage), modified) == "processed"
        assert await importer.process_content(server_id, storage_path, storage, len(storage), modified) == "skipped"
        assert await importer.process_content(server_id, permanent_path, permanent, len(permanent), modified) == "processed"
        current = await session.scalar(select(StorageCurrent))
        snapshots = (await session.scalars(select(StorageSnapshot))).all()
        progression = await session.scalar(select(CharacterPermanentData))
        assert current.data["storage_id"].startswith("42_itemstorage")
        assert current.data["item_count"] == 1
        assert len(snapshots) == 1
        assert progression.player_id == "42"
        assert progression.data["achievement_count"] == 0
    await engine.dispose()
