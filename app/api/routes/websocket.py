import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import resolve_server
from app.core.config import get_settings
from app.core.cors import websocket_origin_allowed
from app.db.models import DomainEvent
from app.db.session import get_session
from app.services.event_service import event_service
from app.websocket.auth import WebSocketAuthError, authenticate_websocket
from app.websocket.manager import ConnectionLimitError, connection_manager
from app.websocket.schemas import SubscriptionMessage

router = APIRouter(prefix="/servers/{server_id}", tags=["websocket"])


def _token(websocket: WebSocket) -> str | None:
    authorization = websocket.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return websocket.query_params.get("token")


async def _socket(websocket: WebSocket, server_id: str, channel: str, after_sequence: int | None, session: AsyncSession):
    settings = get_settings()
    if not settings.websocket_enabled:
        await websocket.close(1008)
        return
    if not websocket_origin_allowed(
        websocket.headers.get("origin"),
        settings.websocket_origins,
        settings.websocket_allow_missing_origin,
    ):
        await websocket.close(4403)
        return
    try:
        server = await resolve_server(session, server_id)
    except HTTPException:
        await websocket.close(4403)
        return
    try:
        principal = authenticate_websocket(_token(websocket), server_id, channel, {str(server.id)})
    except WebSocketAuthError as exc:
        await websocket.close(exc.code)
        return
    try:
        connection = await connection_manager.connect(websocket, str(server.id), channel, principal.user_id)
    except ConnectionLimitError:
        await websocket.close(1008)
        return
    latest = await event_service.latest_sequence(server.id)
    await connection_manager.send_personal(connection, {
        "event": "system.connected", "server_id": str(server.id), "channel": channel,
        "connection_id": connection.connection_id, "sequence": latest, "published_at": datetime.now(UTC).isoformat(),
    })
    if after_sequence is not None and after_sequence < latest:
        replay = await event_service.replay(server.id, after_sequence)
        if replay is None:
            await connection_manager.send_personal(connection, {"event": "system.resync_required", "reason": "event_history_unavailable", "latest_sequence": latest})
        else:
            for event in replay:
                if channel in event_service.channels_for(event):
                    await connection_manager.send_personal(connection, event)
    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw.encode()) > get_settings().websocket_max_message_bytes:
                await connection_manager.disconnect(connection, 1008)
                return
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await connection_manager.send_personal(connection, {"event": "system.error", "message": "invalid JSON"})
                continue
            if message.get("event") == "system.pong":
                connection.last_pong_at = datetime.now(UTC)
                continue
            if channel == "events" and message.get("action") in {"subscribe", "unsubscribe"}:
                subscription = SubscriptionMessage.model_validate(message)
                if subscription.action == "subscribe":
                    await connection_manager.subscribe(connection, subscription.events, subscription.filters)
                else:
                    await connection_manager.unsubscribe(connection, subscription.events)
                await connection_manager.send_personal(connection, {"event": "system.subscription.updated", "events": sorted(connection.subscriptions or set()), "filters": connection.filters})
    except WebSocketDisconnect:
        pass
    except Exception:
        await connection_manager.disconnect(connection, 1011)
        return
    finally:
        await connection_manager.disconnect(connection)


@router.websocket("/ws/kills")
async def ws_kills(websocket: WebSocket, server_id: str, after_sequence: int | None = None, session: AsyncSession = Depends(get_session)):
    await _socket(websocket, server_id, "kills", after_sequence, session)


@router.websocket("/ws/map")
async def ws_map(websocket: WebSocket, server_id: str, after_sequence: int | None = None, session: AsyncSession = Depends(get_session)):
    await _socket(websocket, server_id, "map", after_sequence, session)


@router.websocket("/ws/sync")
async def ws_sync(websocket: WebSocket, server_id: str, after_sequence: int | None = None, session: AsyncSession = Depends(get_session)):
    await _socket(websocket, server_id, "sync", after_sequence, session)


@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket, server_id: str, after_sequence: int | None = None, session: AsyncSession = Depends(get_session)):
    await _socket(websocket, server_id, "events", after_sequence, session)


@router.get("/ws/status")
async def websocket_status(server_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    return {
        "enabled": get_settings().websocket_enabled,
        "connections": connection_manager.status(str(server.id)),
        "latest_sequence": await event_service.latest_sequence(server.id),
        "events_persisted_last_hour": await event_service.persisted_last_hour(server.id),
    }


@router.get("/events")
async def recent_events(server_id: str, after_sequence: int | None = None, event: str | None = None, entity_type: str | None = None, entity_id: str | None = None, date_from: datetime | None = Query(None, alias="from"), date_to: datetime | None = Query(None, alias="to"), limit: int = Query(100, ge=1, le=1000), session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    query = select(DomainEvent).where(DomainEvent.server_id == server.id)
    if after_sequence is not None: query = query.where(DomainEvent.sequence > after_sequence)
    if event: query = query.where(DomainEvent.event_name == event)
    if entity_type: query = query.where(DomainEvent.entity_type == entity_type)
    if entity_id: query = query.where(DomainEvent.entity_id == entity_id)
    if date_from: query = query.where(DomainEvent.occurred_at >= date_from)
    if date_to: query = query.where(DomainEvent.occurred_at <= date_to)
    rows = (await session.scalars(query.order_by(DomainEvent.sequence).limit(limit))).all()
    return [event_service.serialize(row) for row in rows]
