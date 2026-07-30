from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import resolve_server
from app.db.models import CharacterCurrent, CharacterPermanentData, StorageCurrent, VehicleCurrent
from app.db.session import get_session
from app.services.map_service import MapService

characters_router = APIRouter(prefix="/servers/{server_id}/characters", tags=["characters"])
players_router = APIRouter(prefix="/servers/{server_id}/players", tags=["players"])
vehicles_router = APIRouter(prefix="/servers/{server_id}/vehicles", tags=["vehicles"])
storages_router = APIRouter(prefix="/servers/{server_id}/storages", tags=["storages"])


def _entity(model, map_service: MapService) -> dict:
    result = {column.name: getattr(model, column.name) for column in model.__table__.columns if column.name not in {"raw_data", "metadata"}}
    if model.pos_x is not None and model.pos_y is not None:
        result.update(map_service.position(model.pos_x, model.pos_y, model.pos_z))
    observed = model.observed_at
    if observed:
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        age = max(0, int((datetime.now(UTC) - observed).total_seconds()))
        result["source_age_seconds"] = age
        result["position_freshness"] = "fresh" if age <= 15 else "delayed" if age <= 120 else "stale"
    return result


@players_router.get("/online")
async def online_players(server_id: str, session: AsyncSession = Depends(get_session)):
    """Return all log-confirmed online sessions, even before a save is available."""
    server = await resolve_server(session, server_id)
    from app.services.ftp import ftp_sync_manager

    logins = ftp_sync_manager.online_logins(server.id)
    rows = [] if not logins else (await session.scalars(
        select(CharacterCurrent).where(
            CharacterCurrent.server_id == server.id,
            CharacterCurrent.login.in_(logins),
        )
    )).all()
    characters_by_login = {row.login: row for row in rows if row.login}
    now = datetime.now(UTC)
    players = []
    for login in sorted(logins, key=str.casefold):
        row = characters_by_login.get(login)
        observed_at = row.observed_at if row else None
        if observed_at and observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        players.append({
            "login": login,
            "online": True,
            "player_id": row.player_id if row else None,
            "has_character_data": row is not None,
            "has_position": bool(row and row.pos_x is not None and row.pos_y is not None),
            "health": row.health if row else None,
            "observed_at": observed_at,
            "source_age_seconds": max(0, round((now - observed_at).total_seconds(), 1)) if observed_at else None,
        })
    identified_count = sum(player["player_id"] is not None for player in players)
    return {
        "players": players,
        "count": len(players),
        "identified_count": identified_count,
        "pending_character_count": len(players) - identified_count,
        "live_detection": "deadside_log_join_logout",
        "generated_at": now,
    }


@characters_router.get("")
async def characters(server_id: str, limit: int = Query(100, ge=1, le=1000), session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    rows = (await session.scalars(select(CharacterCurrent).where(CharacterCurrent.server_id == server.id).limit(limit))).all()
    service = MapService()
    return [_entity(row, service) for row in rows]


@characters_router.get("/{player_id}")
async def character(server_id: str, player_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    row = await session.scalar(select(CharacterCurrent).where(CharacterCurrent.server_id == server.id, CharacterCurrent.player_id == player_id))
    if row is None:
        raise HTTPException(404, "character not found")
    return _entity(row, MapService())


@characters_router.get("/{player_id}/permanent")
async def permanent_character(server_id: str, player_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    row = await session.scalar(select(CharacterPermanentData).where(
        CharacterPermanentData.server_id == server.id,
        CharacterPermanentData.player_id == player_id,
    ))
    if row is None:
        raise HTTPException(404, "permanent character data not found")
    return {"player_id": row.player_id, **row.data, "observed_at": row.observed_at}


@vehicles_router.get("")
async def vehicles(server_id: str, active: bool | None = None, limit: int = Query(100, ge=1, le=1000), session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    query = select(VehicleCurrent).where(VehicleCurrent.server_id == server.id)
    if active is not None:
        query = query.where(VehicleCurrent.active == active)
    rows = (await session.scalars(query.limit(limit))).all()
    return [_entity(row, MapService()) for row in rows]


@vehicles_router.get("/{vehicle_uid}")
async def vehicle(server_id: str, vehicle_uid: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    row = await session.scalar(select(VehicleCurrent).where(VehicleCurrent.server_id == server.id, VehicleCurrent.vehicle_uid == vehicle_uid))
    if row is None:
        raise HTTPException(404, "vehicle not found")
    return _entity(row, MapService())


@storages_router.get("")
async def storages(server_id: str, player_id: str | None = None, limit: int = Query(100, ge=1, le=1000), session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    query = select(StorageCurrent).where(StorageCurrent.server_id == server.id)
    if player_id is not None:
        query = query.where(StorageCurrent.data["player_id"].as_string() == player_id)
    rows = (await session.scalars(query.order_by(StorageCurrent.observed_at.desc()).limit(limit))).all()
    return [{**row.data, "observed_at": row.observed_at} for row in rows]


@storages_router.get("/{storage_id}")
async def storage(server_id: str, storage_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    row = await session.scalar(select(StorageCurrent).where(
        StorageCurrent.server_id == server.id,
        StorageCurrent.data["storage_id"].as_string() == storage_id,
    ))
    if row is None:
        raise HTTPException(404, "storage not found")
    return {**row.data, "observed_at": row.observed_at}
