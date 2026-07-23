import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import CharacterCurrent, Server
from app.db.session import get_session
from app.main import app


@pytest.mark.asyncio
async def test_live_players_excludes_stale_players_and_vehicles(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'live-map.db').as_posix()}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    server_id = uuid.uuid4()
    async with sessions() as session:
        session.add(Server(id=server_id, slug="live-map", name="Live Map"))
        session.add_all([
            CharacterCurrent(server_id=server_id, player_id="live", login="Live Player", pos_x=-300245, pos_y=-76290.4, pos_z=100, health=88, inventory={}, raw_data={}, source_modified_at=now - timedelta(seconds=10), observed_at=now),
            CharacterCurrent(server_id=server_id, player_id="stale", login="Stale Player", pos_x=-300245, pos_y=-76290.4, pos_z=100, health=100, inventory={}, raw_data={}, source_modified_at=now - timedelta(minutes=10), observed_at=now),
            CharacterCurrent(server_id=server_id, player_id="no-position", login="No Position", pos_x=None, pos_y=None, inventory={}, raw_data={}, source_modified_at=now, observed_at=now),
        ])
        await session.commit()

    async def override_session():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/servers/live-map/map/live-players?max_age_seconds=120")
        assert response.status_code == 200
        payload = response.json()
        assert payload["count"] == 1
        assert payload["live_detection"] == "ftp_source_modified_at"
        assert payload["max_age_seconds"] == 120
        assert payload["players"][0]["player_id"] == "live"
        assert payload["players"][0]["login"] == "Live Player"
        assert payload["players"][0]["source_age_seconds"] < 120
        assert payload["players"][0]["map_position"]["inside_map"] is True
        assert "vehicles" not in payload
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
