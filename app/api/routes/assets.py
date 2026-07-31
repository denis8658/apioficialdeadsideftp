from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/maps", tags=["map"])

_MAP_ROOT = Path(__file__).resolve().parents[2] / "static" / "maps" / "mirny"
_MIRNY_IMAGE = _MAP_ROOT / "deadside_map.png"
_MIRNY_TILE_LIMITS = {1: (10, 11), 2: (5, 6), 3: (3, 3), 4: (2, 2)}


@router.get(
    "/mirny/image",
    response_class=FileResponse,
    responses={200: {"content": {"image/png": {}}}},
)
async def mirny_image() -> FileResponse:
    return FileResponse(
        _MIRNY_IMAGE,
        media_type="image/png",
        filename="deadside_map.png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get(
    "/mirny/tiles/lod_{lod}/map_{x}_{y}.png",
    response_class=FileResponse,
    responses={200: {"content": {"image/png": {}}}},
)
async def mirny_tile(lod: int, x: int, y: int) -> FileResponse:
    limits = _MIRNY_TILE_LIMITS.get(lod)
    if limits is None or x < 0 or y < 0 or x >= limits[0] or y >= limits[1]:
        raise HTTPException(404, "map tile not found")
    tile = _MAP_ROOT / f"lod_{lod}" / f"map_{x}_{y}.png"
    if not tile.is_file():
        raise HTTPException(404, "map tile not found")
    return FileResponse(
        tile,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
