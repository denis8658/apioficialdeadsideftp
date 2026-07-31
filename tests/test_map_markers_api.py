import uuid
from datetime import UTC, datetime
from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.ftp import ftp_sync_manager
from app.db.base import Base
from app.db.models import CharacterCurrent, Server, VehicleCurrent
from app.db.session import get_session
from app.main import app


@pytest.mark.asyncio
async def test_map_markers_are_ftp_backed_and_only_include_active_entities(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'markers.db').as_posix()}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    server_id = uuid.uuid4()
    now = datetime.now(UTC)
    async with sessions() as session:
        session.add(Server(id=server_id, slug="markers-test", name="Markers Test"))
        session.add(CharacterCurrent(
            server_id=server_id, player_id="online", login="Online Player", map_name="world_0",
            pos_x=10, pos_y=20, pos_z=30, inventory={}, raw_data={}, observed_at=now,
        ))
        session.add(CharacterCurrent(
            server_id=server_id, player_id="offline", login="Offline Player", map_name="world_0",
            pos_x=10, pos_y=20, pos_z=30, inventory={}, raw_data={}, observed_at=now,
        ))
        session.add(VehicleCurrent(
            server_id=server_id, vehicle_uid="active-car", display_name="UAZ",
            pos_x=40, pos_y=50, pos_z=60, rotation={}, inventory={}, metadata_json={}, raw_data={},
            active=True, observed_at=now,
        ))
        session.add(VehicleCurrent(
            server_id=server_id, vehicle_uid="inactive-car", display_name="UAZ",
            pos_x=40, pos_y=50, pos_z=60, rotation={}, inventory={}, metadata_json={}, raw_data={},
            active=False, observed_at=now,
        ))
        await session.commit()

    async def override_session():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(ftp_sync_manager, "online_player_ids", Mock(return_value={"online"}))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/servers/markers-test/map/markers")
        assert response.status_code == 200
        payload = response.json()
        assert payload["source_scope"] == "ftp_only"
        assert payload["counts"] == {"players": 1, "vehicles": 1}
        assert {marker["id"] for marker in payload["markers"]} == {"player:online", "vehicle:active-car"}
        assert all(marker["map_position"]["inside_map"] for marker in payload["markers"])
        assert all(marker["source"].startswith("ftp.") for marker in payload["markers"])
        assert payload["excluded_without_exact_coordinates"] == ["storages"]
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
