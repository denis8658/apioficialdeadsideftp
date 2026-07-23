import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.ftp import ftp_sync_manager
from app.db.base import Base
from app.db.models import CharacterCurrent, CharacterPermanentData, DeathEvent, Server, StorageCurrent, VehicleCurrent
from app.db.session import get_session
from app.main import app
from app.services.event_service import event_service


@pytest.mark.asyncio
async def test_every_api_endpoint_returns_its_success_contract(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'all-endpoints.db').as_posix()}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    server_id = uuid.uuid4()
    kill_id = uuid.uuid4()
    storage_id = "p1_itemstorage_world_0_X08_Y07_ItemStorage01_2"
    now = datetime(2026, 7, 21, 22, 15, tzinfo=UTC)
    async with sessions() as session:
        session.add(Server(id=server_id, slug="endpoint-test", name="Endpoint Test"))
        session.add(CharacterCurrent(server_id=server_id, player_id="p1", login="Player", map_name="world_0", pos_x=10, pos_y=20, pos_z=30, inventory={}, raw_data={}, source_modified_at=datetime.now(UTC), observed_at=now))
        session.add(CharacterPermanentData(server_id=server_id, player_id="p1", data={"achievements": []}, observed_at=now))
        session.add(VehicleCurrent(server_id=server_id, vehicle_uid="v1", display_name="UAZ", pos_x=40, pos_y=50, pos_z=60, rotation={}, inventory={}, metadata_json={}, raw_data={}, active=True, observed_at=now))
        session.add(StorageCurrent(server_id=server_id, data={"storage_id": storage_id, "player_id": "p1", "items": []}, observed_at=now))
        session.add(DeathEvent(
            id=kill_id, server_id=server_id, event_time=now, event_type="player_kill",
            victim_id="p2", victim_name="Victim", victim_type="player", victim_platform="PS5",
            killer_id="p1", killer_name="Player", killer_type="player", killer_platform="XSX",
            weapon_name="AR4", distance_meters=100, is_player_kill=True, is_suicide=False, is_environmental=False,
            source_file="day.csv", source_line=1, fingerprint="f" * 64, raw_data={},
        ))
        await session.commit()

    async def override_session():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(ftp_sync_manager, "test_connection", AsyncMock(return_value={"success": True, "authenticated": True}))
    monkeypatch.setattr(ftp_sync_manager, "discover", AsyncMock(return_value={"paths": {}, "entries_scanned": 1}))
    monkeypatch.setattr(ftp_sync_manager, "status", Mock(return_value={"state": "stopped", "connection": "disconnected"}))
    monkeypatch.setattr(ftp_sync_manager, "run_once", AsyncMock(return_value={"status": "completed"}))
    monkeypatch.setattr(ftp_sync_manager, "start", Mock(return_value={"status": "started"}))
    monkeypatch.setattr(ftp_sync_manager, "stop", AsyncMock(return_value={"status": "stopped"}))
    monkeypatch.setattr(event_service, "latest_sequence", AsyncMock(return_value=0))
    monkeypatch.setattr(event_service, "persisted_last_hour", AsyncMock(return_value=0))

    slug = "endpoint-test"
    calls = [
        ("GET", "/api/v1/health", None, "GET /api/v1/health"),
        ("GET", "/api/v1/health/ready", None, "GET /api/v1/health/ready"),
        ("GET", "/api/v1/version", None, "GET /api/v1/version"),
        ("GET", "/api/v1/diagnostics/parsers", None, "GET /api/v1/diagnostics/parsers"),
        ("GET", "/api/v1/diagnostics/cors", None, "GET /api/v1/diagnostics/cors"),
        ("GET", "/api/v1/maps/mirny/image", None, "GET /api/v1/maps/mirny/image"),
        ("GET", "/api/v1/servers", None, "GET /api/v1/servers"),
        ("POST", "/api/v1/servers", {"json": {"slug": "created-server", "name": "Created"}}, "POST /api/v1/servers"),
        ("GET", f"/api/v1/servers/{slug}", None, "GET /api/v1/servers/{server_id}"),
        ("PATCH", f"/api/v1/servers/{slug}", {"json": {"name": "Renamed"}}, "PATCH /api/v1/servers/{server_id}"),
        ("GET", f"/api/v1/servers/{slug}/characters", None, "GET /api/v1/servers/{server_id}/characters"),
        ("GET", f"/api/v1/servers/{slug}/characters/p1", None, "GET /api/v1/servers/{server_id}/characters/{player_id}"),
        ("GET", f"/api/v1/servers/{slug}/characters/p1/permanent", None, "GET /api/v1/servers/{server_id}/characters/{player_id}/permanent"),
        ("GET", f"/api/v1/servers/{slug}/vehicles", None, "GET /api/v1/servers/{server_id}/vehicles"),
        ("GET", f"/api/v1/servers/{slug}/vehicles/v1", None, "GET /api/v1/servers/{server_id}/vehicles/{vehicle_uid}"),
        ("GET", f"/api/v1/servers/{slug}/storages", None, "GET /api/v1/servers/{server_id}/storages"),
        ("GET", f"/api/v1/servers/{slug}/storages/{storage_id}", None, "GET /api/v1/servers/{server_id}/storages/{storage_id}"),
        ("POST", f"/api/v1/servers/{slug}/ftp/test", None, "POST /api/v1/servers/{server_id}/ftp/test"),
        ("POST", f"/api/v1/servers/{slug}/ftp/discover", None, "POST /api/v1/servers/{server_id}/ftp/discover"),
        ("GET", f"/api/v1/servers/{slug}/ftp/status", None, "GET /api/v1/servers/{server_id}/ftp/status"),
        ("GET", f"/api/v1/servers/{slug}/sync/status", None, "GET /api/v1/servers/{server_id}/sync/status"),
        ("POST", f"/api/v1/servers/{slug}/sync/run", None, "POST /api/v1/servers/{server_id}/sync/run"),
        ("POST", f"/api/v1/servers/{slug}/sync/start", None, "POST /api/v1/servers/{server_id}/sync/start"),
        ("POST", f"/api/v1/servers/{slug}/sync/stop", None, "POST /api/v1/servers/{server_id}/sync/stop"),
        ("GET", f"/api/v1/servers/{slug}/ws/status", None, "GET /api/v1/servers/{server_id}/ws/status"),
        ("GET", f"/api/v1/servers/{slug}/events", None, "GET /api/v1/servers/{server_id}/events"),
        ("GET", f"/api/v1/servers/{slug}/map/config", None, "GET /api/v1/servers/{server_id}/map/config"),
        ("POST", f"/api/v1/servers/{slug}/map/convert", {"json": {"x": 10, "y": 20, "z": 30}}, "POST /api/v1/servers/{server_id}/map/convert"),
        ("POST", f"/api/v1/servers/{slug}/map/reverse-convert", {"json": {"x": 640, "y": -896}}, "POST /api/v1/servers/{server_id}/map/reverse-convert"),
        ("GET", f"/api/v1/servers/{slug}/map/entities", None, "GET /api/v1/servers/{server_id}/map/entities"),
        ("GET", f"/api/v1/servers/{slug}/map/live-players", None, "GET /api/v1/servers/{server_id}/map/live-players"),
        ("GET", f"/api/v1/servers/{slug}/kills", None, "GET /api/v1/servers/{server_id}/kills"),
        ("GET", f"/api/v1/servers/{slug}/kills/latest", None, "GET /api/v1/servers/{server_id}/kills/latest"),
        ("GET", f"/api/v1/servers/{slug}/kills/feed", None, "GET /api/v1/servers/{server_id}/kills/feed"),
        ("GET", f"/api/v1/servers/{slug}/kills/statistics", None, "GET /api/v1/servers/{server_id}/kills/statistics"),
        ("GET", f"/api/v1/servers/{slug}/kills/leaderboard", None, "GET /api/v1/servers/{server_id}/kills/leaderboard"),
        ("GET", f"/api/v1/servers/{slug}/kills/weapons", None, "GET /api/v1/servers/{server_id}/kills/weapons"),
        ("GET", f"/api/v1/servers/{slug}/kills/timeline", None, "GET /api/v1/servers/{server_id}/kills/timeline"),
        ("GET", f"/api/v1/servers/{slug}/kills/head-to-head?player_a=p1&player_b=p2", None, "GET /api/v1/servers/{server_id}/kills/head-to-head"),
        ("GET", f"/api/v1/servers/{slug}/kills/geojson", None, "GET /api/v1/servers/{server_id}/kills/geojson"),
        ("GET", f"/api/v1/servers/{slug}/kills/heatmap", None, "GET /api/v1/servers/{server_id}/kills/heatmap"),
        ("GET", f"/api/v1/servers/{slug}/kills/{kill_id}", None, "GET /api/v1/servers/{server_id}/kills/{kill_id}"),
        ("GET", f"/api/v1/servers/{slug}/players/p1/kills", None, "GET /api/v1/servers/{server_id}/players/{player_id}/kills"),
        ("GET", f"/api/v1/servers/{slug}/players/p1/deaths", None, "GET /api/v1/servers/{server_id}/players/{player_id}/deaths"),
        ("GET", f"/api/v1/servers/{slug}/players/p1/combat-stats", None, "GET /api/v1/servers/{server_id}/players/{player_id}/combat-stats"),
        ("GET", f"/api/v1/servers/{slug}/players/p1/rivals", None, "GET /api/v1/servers/{server_id}/players/{player_id}/rivals"),
        ("GET", f"/api/v1/servers/{slug}/players/p1/victims", None, "GET /api/v1/servers/{server_id}/players/{player_id}/victims"),
        ("GET", f"/api/v1/servers/{slug}/players/p1/killers", None, "GET /api/v1/servers/{server_id}/players/{player_id}/killers"),
    ]
    tested = set()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for method, path, options, route_key in calls:
                response = await client.request(method, path, **(options or {}))
                assert 200 <= response.status_code < 300, f"{method} {path}: {response.status_code} {response.text}"
                tested.add(route_key)
            created = (await client.get("/api/v1/servers/created-server")).json()
            response = await client.delete(f"/api/v1/servers/{created['id']}")
            assert response.status_code == 204
            tested.add("DELETE /api/v1/servers/{server_id}")

        registered = {
            f"{method} {route.path}"
            for route in app.routes if route.path.startswith("/api/v1")
            for method in (getattr(route, "methods", None) or set())
        }
        assert tested == registered, f"untested={sorted(registered - tested)}, unknown={sorted(tested - registered)}"
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
