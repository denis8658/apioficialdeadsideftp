from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import resolve_server
from app.db.session import get_session
from app.services.ftp import FTPIntegrationError, ftp_sync_manager

router = APIRouter(prefix="/servers/{server_id}", tags=["ftp", "sync"])


def _safe_error(exc: FTPIntegrationError) -> dict:
    return {"success": False, "error_code": exc.code, "message": exc.safe_message, "tested_at": datetime.now(UTC)}


@router.post("/ftp/test")
async def test_ftp(server_id: str, session: AsyncSession = Depends(get_session)):
    await resolve_server(session, server_id)
    try:
        return await ftp_sync_manager.test_connection()
    except FTPIntegrationError as exc:
        return _safe_error(exc)


@router.post("/ftp/discover")
async def discover_ftp(server_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    try:
        return await ftp_sync_manager.discover(server.id)
    except FTPIntegrationError as exc:
        return _safe_error(exc)


@router.get("/ftp/status")
@router.get("/sync/status")
async def sync_status(server_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    return ftp_sync_manager.status(server.id)


@router.post("/sync/run")
async def sync_run(server_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    try:
        return await ftp_sync_manager.run_once(server.id)
    except FTPIntegrationError as exc:
        return _safe_error(exc)


@router.post("/sync/start")
async def sync_start(server_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    return ftp_sync_manager.start(server.id)


@router.post("/sync/stop")
async def sync_stop(server_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    return await ftp_sync_manager.stop(server.id)
