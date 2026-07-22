from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.db.session import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(session: AsyncSession = Depends(get_session)):
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "unavailable", "database": "disconnected"}, status_code=503)
    return {"status": "ok", "database": "connected"}


@router.get("/version")
async def version() -> dict:
    return {"name": "Deadside Data API", "version": __version__}
