from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(prefix="/maps", tags=["map"])

_MAP_ROOT = Path(__file__).resolve().parents[2] / "static" / "maps" / "mirny"
_MIRNY_IMAGE = _MAP_ROOT / "deadside_map.png"


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
