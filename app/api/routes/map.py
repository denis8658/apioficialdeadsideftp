from fastapi import APIRouter, Depends
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


@router.get("/config")
async def map_config(server_id: str, session: AsyncSession = Depends(get_session)):
    await resolve_server(session, server_id)
    service = MapService()
    s = service.settings
    return {"calibration_name": service.calibration_name, "calibration_version": service.calibration_version, "calibration_status": service.calibration_status, "bounds": {"min_x": s.map_min_x, "max_x": s.map_max_x, "min_y": s.map_min_y, "max_y": s.map_max_y}, "origin": {"x": s.map_origin_x, "y": s.map_origin_y}, "unreal_units_per_map_unit": s.unreal_units_per_map_unit, "image": {"url": "/api/v1/maps/mirny/image", "width": 1280, "height": 1408}, "tiles": {"url_template": "/static/maps/mirny/tiles/map_{x}_{y}.png", "tile_size": 512, "columns": 3, "rows": 3, "content_width": 1280, "content_height": 1408}}


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
