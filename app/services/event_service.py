import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from app.core.config import get_settings
from app.db.models import DomainEvent, ServerEventSequence
from app.db.session import SessionLocal
from app.websocket.manager import connection_manager
from app.websocket.schemas import EventEnvelope

logger = logging.getLogger(__name__)


class EventService:
    def __init__(self):
        self.settings = get_settings()
        self._sequence_locks: dict[uuid.UUID, asyncio.Lock] = {}

    async def publish_after_commit(self, *, event: str, server_id: uuid.UUID, data: dict[str, Any], occurred_at: datetime | None = None, entity_type: str | None = None, entity_id: str | None = None, correlation_id: str | None = None, source: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Persist and broadcast only after the caller's domain transaction committed."""
        if not self.settings.websocket_enabled:
            return None
        try:
            sequence = await self._next_sequence(server_id)
            envelope = EventEnvelope(
                event=event, server_id=str(server_id), sequence=sequence,
                occurred_at=occurred_at or datetime.now(UTC), data=data,
                entity_type=entity_type, entity_id=entity_id,
                correlation_id=correlation_id, source=source, metadata=metadata or {},
            )
            payload = envelope.model_dump(mode="json")
            if self.settings.websocket_persist_events and not event.startswith("system."):
                async with SessionLocal() as session:
                    session.add(DomainEvent(
                        id=envelope.event_id, server_id=server_id, sequence=sequence, event_name=event,
                        entity_type=entity_type, entity_id=entity_id, occurred_at=envelope.occurred_at,
                        published_at=envelope.published_at, payload=data, correlation_id=correlation_id,
                        source=source, metadata_json=metadata or {},
                    ))
                    await session.commit()
            await self._broadcast(payload)
            return payload
        except Exception:
            logger.exception("Domain event publication failed", extra={"server_id": str(server_id), "event_name": event})
            return None

    async def _next_sequence(self, server_id: uuid.UUID) -> int:
        lock = self._sequence_locks.setdefault(server_id, asyncio.Lock())
        async with lock:
            async with SessionLocal() as session:
                if session.bind and session.bind.dialect.name == "postgresql":
                    statement = postgresql_insert(ServerEventSequence).values(server_id=server_id, value=1).on_conflict_do_update(
                        index_elements=[ServerEventSequence.server_id],
                        set_={"value": ServerEventSequence.value + 1, "updated_at": func.now()},
                    ).returning(ServerEventSequence.value)
                    value = await session.scalar(statement)
                    await session.commit()
                    return int(value)
                row = await session.scalar(select(ServerEventSequence).where(ServerEventSequence.server_id == server_id).with_for_update())
                if row is None:
                    row = ServerEventSequence(server_id=server_id, value=1)
                    session.add(row)
                else:
                    row.value += 1
                await session.commit()
                return row.value

    async def _broadcast(self, payload: dict[str, Any]):
        server_id = payload["server_id"]
        channels = self.channels_for(payload)
        await asyncio.gather(*(connection_manager.broadcast_to_channel(server_id, channel, payload) for channel in channels), return_exceptions=True)

    @staticmethod
    def channels_for(payload: dict[str, Any]) -> set[str]:
        event = payload["event"]
        channels = {"events"}
        if event in {"kill.created", "kill.updated", "death.created"}:
            channels.add("kills")
        if event.startswith(("character.", "vehicle.")):
            channels.add("map")
        if event == "storage.updated" and payload.get("data", {}).get("map_position"):
            channels.add("map")
        if event == "kill.created" and payload.get("data", {}).get("map_position"):
            channels.add("map")
        if event.startswith("sync.") or event.startswith("ftp."):
            channels.add("sync")
        return channels

    async def latest_sequence(self, server_id: uuid.UUID) -> int:
        async with SessionLocal() as session:
            return int(await session.scalar(select(ServerEventSequence.value).where(ServerEventSequence.server_id == server_id)) or 0)

    async def replay(self, server_id: uuid.UUID, after_sequence: int, limit: int = 1000) -> list[dict[str, Any]] | None:
        if not self.settings.websocket_persist_events:
            return None
        async with SessionLocal() as session:
            rows = (await session.scalars(select(DomainEvent).where(DomainEvent.server_id == server_id, DomainEvent.sequence > after_sequence).order_by(DomainEvent.sequence).limit(limit))).all()
            return [self.serialize(row) for row in rows]

    async def persisted_last_hour(self, server_id: uuid.UUID) -> int:
        async with SessionLocal() as session:
            return int(await session.scalar(select(func.count()).select_from(DomainEvent).where(DomainEvent.server_id == server_id, DomainEvent.created_at >= datetime.now(UTC) - timedelta(hours=1))) or 0)

    async def cleanup(self) -> int:
        cutoff = datetime.now(UTC) - timedelta(hours=self.settings.websocket_event_retention_hours)
        async with SessionLocal() as session:
            result = await session.execute(delete(DomainEvent).where(DomainEvent.created_at < cutoff))
            await session.commit()
            return result.rowcount or 0

    @staticmethod
    def serialize(row: DomainEvent) -> dict[str, Any]:
        return EventEnvelope(
            event_id=row.id, event=row.event_name, server_id=str(row.server_id), sequence=row.sequence,
            occurred_at=row.occurred_at, published_at=row.published_at, data=row.payload,
            entity_type=row.entity_type, entity_id=row.entity_id, correlation_id=row.correlation_id,
            source=row.source, metadata=row.metadata_json,
        ).model_dump(mode="json")


event_service = EventService()


class EventRetentionService:
    def __init__(self, service: EventService):
        self.service = service
        self._task: asyncio.Task | None = None

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="websocket-event-retention")

    async def stop(self):
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _run(self):
        try:
            while True:
                await asyncio.sleep(3600)
                try:
                    await self.service.cleanup()
                except Exception:
                    logger.exception("Domain event retention cleanup failed")
        except asyncio.CancelledError:
            raise


event_retention_service = EventRetentionService(event_service)
