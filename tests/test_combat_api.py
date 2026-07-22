import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import DeathEvent, Server
from app.db.session import get_session
from app.main import app


def death(server_id, *, fingerprint, event_type="player_kill", killer_id="a", victim_id="b", weapon="AR4", distance=120.0):
    return DeathEvent(
        server_id=server_id, event_time=datetime(2026, 7, 21, 22, 0, tzinfo=UTC), event_type=event_type,
        victim_id=victim_id, victim_name="Victim", victim_type="player", victim_platform="PC",
        killer_id=killer_id, killer_name="Killer", killer_type="environment" if event_type == "environmental_death" else "player", killer_platform="PC",
        weapon_name=weapon, cause="falling" if event_type == "environmental_death" else None, distance_meters=distance,
        is_player_kill=event_type == "player_kill", is_suicide=False, is_environmental=event_type == "environmental_death",
        source_file="day.csv", source_line=1, fingerprint=fingerprint, raw_data={},
    )


@pytest.mark.asyncio
async def test_kill_endpoints_filter_calculate_and_hide_raw_data(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'api.db').as_posix()}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    server_id = uuid.uuid4()
    async with sessions() as session:
        session.add(Server(id=server_id, slug="combat-api", name="Combat API"))
        session.add(death(server_id, fingerprint="1" * 64))
        session.add(death(server_id, fingerprint="2" * 64, event_type="environmental_death", killer_id="b", victim_id="b", weapon=None, distance=0))
        await session.commit()

    async def override_session():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/servers/combat-api/kills", params={"weapon": "AR4"})
            assert response.status_code == 200
            assert len(response.json()) == 1
            assert "raw_data" not in response.json()[0]
            assert (await client.get("/api/v1/servers/combat-api/kills/latest")).json()[0]["weapon_name"] == "AR4"
            stats = (await client.get("/api/v1/servers/combat-api/kills/statistics")).json()
            assert stats["by_event_type"] == {"player_kill": 1, "environmental_death": 1}
            board = (await client.get("/api/v1/servers/combat-api/kills/leaderboard")).json()
            assert board["items"][0]["kills"] == 1
            combat = (await client.get("/api/v1/servers/combat-api/players/a/combat-stats")).json()
            assert combat["kills"] == 1 and combat["kd_ratio"] is None
            unavailable = (await client.get("/api/v1/servers/combat-api/kills/heatmap")).json()
            assert unavailable == {"available": False, "reason": "Deathlog sem coordenadas de morte."}
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
