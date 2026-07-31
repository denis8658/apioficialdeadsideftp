from fastapi import APIRouter, Depends
from datetime import UTC, datetime

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import resolve_server
from app.db.models import CharacterCurrent, VehicleCurrent
from app.db.session import get_session
from app.services.map_service import MapService

router = APIRouter(prefix="/servers/{server_id}/map", tags=["map"])


class WorldPoint(BaseModel):
    x: float
    y: float
    z: float | None = None


class MapPointIn(BaseModel):
    x: float
    y: float


def _observed_age_seconds(observed_at: datetime, now: datetime) -> float:
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    return max(0, round((now - observed_at).total_seconds(), 1))


def _vehicle_marker_icon(row: VehicleCurrent) -> str:
    identity = f"{row.display_name or ''} {row.actor_id or ''}".casefold()
    if any(token in identity for token in ("boat", "barco", "water")):
        return "boat"
    if any(token in identity for token in ("bike", "moto", "motorcycle")):
        return "bike"
    return "car"


@router.get("/config")
async def map_config(server_id: str, session: AsyncSession = Depends(get_session)):
    await resolve_server(session, server_id)
    service = MapService()
    s = service.settings
    return {"calibration_name": service.calibration_name, "calibration_version": service.calibration_version, "calibration_status": service.calibration_status, "bounds": {"min_x": s.map_min_x, "max_x": s.map_max_x, "min_y": s.map_min_y, "max_y": s.map_max_y}, "origin": {"x": s.map_origin_x, "y": s.map_origin_y}, "unreal_units_per_map_unit": s.unreal_units_per_map_unit, "image": {"url": "/api/v1/maps/mirny/image?v=ds-info-lod1-20260730", "width": 1280, "height": 1408}, "tiles": {"url_template": "/static/maps/mirny/tiles/map_{x}_{y}.png?v=ds-info-lod1-20260730", "tile_size": 512, "columns": 3, "rows": 3, "content_width": 1280, "content_height": 1408}}


@router.post("/convert")
async def convert(server_id: str, point: WorldPoint, session: AsyncSession = Depends(get_session)):
    await resolve_server(session, server_id)
    return MapService().position(point.x, point.y, point.z)


@router.post("/reverse-convert")
async def reverse_convert(server_id: str, point: MapPointIn, session: AsyncSession = Depends(get_session)):
    await resolve_server(session, server_id)
    world = MapService().map_to_deadside(point.x, point.y)
    return {"world_position": {"x": world.x, "y": world.y}}


@router.get("/entities")
async def entities(server_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    service = MapService()
    characters = (await session.scalars(select(CharacterCurrent).where(CharacterCurrent.server_id == server.id))).all()
    vehicles = (await session.scalars(select(VehicleCurrent).where(VehicleCurrent.server_id == server.id, VehicleCurrent.active.is_(True)))).all()
    def mapped(row, identifier):
        if row.pos_x is None or row.pos_y is None:
            return None
        return {"id": getattr(row, identifier), **service.position(row.pos_x, row.pos_y, row.pos_z)}
    return {"characters": [item for row in characters if (item := mapped(row, "player_id"))], "vehicles": [item for row in vehicles if (item := mapped(row, "vehicle_uid"))]}


@router.get("/markers")
async def ftp_markers(server_id: str, session: AsyncSession = Depends(get_session)):
    """Map markers backed only by entities and coordinates read from the server FTP."""
    server = await resolve_server(session, server_id)
    from app.core.config import get_settings
    from app.services.ftp import ftp_sync_manager

    service = MapService()
    now = datetime.now(UTC)
    online_ids = ftp_sync_manager.online_player_ids(server.id)
    characters = [] if not online_ids else (await session.scalars(
        select(CharacterCurrent).where(
            CharacterCurrent.server_id == server.id,
            CharacterCurrent.player_id.in_(online_ids),
            CharacterCurrent.pos_x.is_not(None),
            CharacterCurrent.pos_y.is_not(None),
        )
    )).all()
    vehicles = (await session.scalars(
        select(VehicleCurrent).where(
            VehicleCurrent.server_id == server.id,
            VehicleCurrent.active.is_(True),
            VehicleCurrent.pos_x.is_not(None),
            VehicleCurrent.pos_y.is_not(None),
        )
    )).all()

    markers = []
    for row in characters:
        position = service.position(row.pos_x, row.pos_y, row.pos_z)
        if not position["map_position"]["inside_map"]:
            continue
        markers.append({
            "id": f"player:{row.player_id}",
            "entity_id": row.player_id,
            "kind": "player",
            "icon": "player",
            "label": row.login or row.player_id,
            "source": "ftp.character",
            "player_id": row.player_id,
            "login": row.login,
            "health": row.health,
            "rot_yaw": row.rot_yaw,
            "observed_at": row.observed_at,
            "source_modified_at": row.source_modified_at,
            "source_age_seconds": _observed_age_seconds(row.observed_at, now),
            **position,
        })
    for row in vehicles:
        position = service.position(row.pos_x, row.pos_y, row.pos_z)
        if not position["map_position"]["inside_map"]:
            continue
        markers.append({
            "id": f"vehicle:{row.vehicle_uid}",
            "entity_id": row.vehicle_uid,
            "kind": "vehicle",
            "icon": _vehicle_marker_icon(row),
            "label": row.display_name or row.actor_id or row.vehicle_uid,
            "source": "ftp.vehicle",
            "vehicle_uid": row.vehicle_uid,
            "display_name": row.display_name,
            "actor_id": row.actor_id,
            "fuel": row.fuel,
            "durability": row.durability,
            "lock_state": row.lock_state,
            "active": row.active,
            "observed_at": row.observed_at,
            "source_modified_at": row.source_modified_at,
            "source_age_seconds": _observed_age_seconds(row.observed_at, now),
            **position,
        })

    player_count = sum(marker["kind"] == "player" for marker in markers)
    vehicle_count = sum(marker["kind"] == "vehicle" for marker in markers)
    return {
        "markers": markers,
        "count": len(markers),
        "counts": {"players": player_count, "vehicles": vehicle_count},
        "source_scope": "ftp_only",
        "coordinate_sources": ["character_saves", "vehicle_saves"],
        "excluded_without_exact_coordinates": ["storages"],
        "refresh_interval_seconds": get_settings().ftp_live_position_interval_seconds,
        "generated_at": now,
    }


@router.get("/live-players")
async def live_players(
    server_id: str,
    max_age_seconds: int | None = Query(default=None, ge=1, le=60),
    session: AsyncSession = Depends(get_session),
):
    """Return only players with an active session confirmed by Deadside.log."""
    server = await resolve_server(session, server_id)
    from app.core.config import get_settings

    now = datetime.now(UTC)
    from app.services.ftp import ftp_sync_manager

    online_ids = ftp_sync_manager.online_player_ids(server.id)
    rows = [] if not online_ids else (await session.scalars(
        select(CharacterCurrent).where(
            CharacterCurrent.server_id == server.id,
            CharacterCurrent.player_id.in_(online_ids),
            CharacterCurrent.pos_x.is_not(None),
            CharacterCurrent.pos_y.is_not(None),
        ).order_by(CharacterCurrent.observed_at.desc())
    )).all()
    service = MapService()
    players = []
    for row in rows:
        position = service.position(row.pos_x, row.pos_y, row.pos_z)
        if not position["map_position"]["inside_map"]:
            continue
        players.append({
            "id": row.player_id,
            "player_id": row.player_id,
            "login": row.login,
            "health": row.health,
            "rot_yaw": row.rot_yaw,
            "source_modified_at": row.source_modified_at,
            "source_age_seconds": _observed_age_seconds(row.observed_at, now),
            "observed_at": row.observed_at,
            **position,
        })
    return {
        "players": players,
        "count": len(players),
        "max_age_seconds": max_age_seconds,
        "position_poll_interval_seconds": get_settings().ftp_live_position_interval_seconds,
        "live_detection": "deadside_log_join_logout",
        "generated_at": now,
    }
