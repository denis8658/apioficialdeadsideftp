import hashlib
import logging
import re
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import (
    CharacterCurrent,
    CharacterPermanentData,
    CharacterPositionHistory,
    CharacterSnapshot,
    DeathEvent,
    FileCategory,
    RemoteFile,
    Server,
    SyncRun,
    StorageCurrent,
    StorageSnapshot,
    VehicleCurrent,
    VehiclePositionHistory,
    VehicleSnapshot,
)
from app.parsers.base import ParseError
from app.parsers.registry import parser_for
from app.services.event_service import event_service
from app.services.map_service import MapService

logger = logging.getLogger(__name__)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def categorize_path(path: str) -> FileCategory:
    normalized = path.replace("\\", "/").lower()
    if re.search(r"/characters\d+(?:-\d+)?/world_\d+/[^/]+\.sav$", normalized):
        return FileCategory.character
    if "/characters_nowipe/" in normalized and normalized.endswith(".sav"):
        return FileCategory.character_nowipe
    if re.search(r"/new_vehicles\d+(?:-\d+)?/world_\d+/new_vehicles\.sav$", normalized):
        return FileCategory.vehicle
    if "/storages" in normalized and normalized.endswith(".sav"):
        return FileCategory.storage
    if "/deathlogs/" in normalized and normalized.endswith(".csv"):
        return FileCategory.deathlog
    if normalized.endswith(("admin.conf", "server.info")) or "/config/linuxserver/" in normalized:
        return FileCategory.config
    if "/logs/" in normalized and normalized.endswith(".log"):
        return FileCategory.log
    if PurePosixPath(normalized).name.startswith("bases"):
        return FileCategory.base
    return FileCategory.unknown


class ZipImporter:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = get_settings()

    async def import_archive(self, archive: Path, server_slug: str, server_name: str | None = None) -> dict[str, Any]:
        server = await self._get_or_create_server(server_slug, server_name or server_slug)
        run = SyncRun(server_id=server.id, status="running")
        self.session.add(run)
        await self.session.commit()
        server_id = server.id
        run_id = run.id
        counts = {"seen": 0, "processed": 0, "skipped": 0, "failed": 0}
        try:
            with zipfile.ZipFile(archive) as source:
                for info in source.infolist():
                    if info.is_dir():
                        continue
                    counts["seen"] += 1
                    content = source.read(info)
                    outcome = await self._process_file(server_id, info, content)
                    counts[outcome] += 1
            run.status = "completed"
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            logger.exception("zip import failed", extra={"archive": str(archive)})
            raise
        finally:
            run.files_seen = counts["seen"]
            run.files_processed = counts["processed"]
            run.files_failed = counts["failed"]
            run.finished_at = datetime.now(UTC)
            await self.session.commit()
        return {"server_id": str(server_id), "sync_run_id": str(run_id), **counts}

    async def _get_or_create_server(self, slug: str, name: str) -> Server:
        server = await self.session.scalar(select(Server).where(Server.slug == slug))
        if server is None:
            server = Server(slug=slug, name=name)
            self.session.add(server)
            await self.session.flush()
        return server

    async def _process_file(self, server_id: uuid.UUID, info: zipfile.ZipInfo, content: bytes) -> str:
        path = info.filename
        modified = datetime(*info.date_time, tzinfo=UTC)
        return await self.process_content(server_id, path, content, info.file_size, modified)

    async def process_content(self, server_id: uuid.UUID, path: str, content: bytes, remote_size: int, modified: datetime | None) -> str:
        """Ingest bytes from any transport using the existing parser registry and transaction."""
        digest = sha256_bytes(content)
        category = categorize_path(path)
        remote = await self.session.scalar(select(RemoteFile).where(RemoteFile.server_id == server_id, RemoteFile.remote_path == path))
        observed = datetime.now(UTC)
        modified = modified or observed
        if remote and remote.content_hash == digest and remote.status in {"processed", "metadata_only", "unsupported"}:
            remote.last_seen_at = observed
            await self.session.commit()
            return "skipped"
        if remote is None:
            remote = RemoteFile(server_id=server_id, remote_path=path, category=category, remote_size=remote_size)
            self.session.add(remote)
        remote.category = category
        remote.remote_size = remote_size
        remote.remote_modified_at = modified
        remote.content_hash = digest
        remote.last_seen_at = observed
        remote.last_downloaded_at = observed
        parser = parser_for(category)
        if parser is None:
            remote.status = "metadata_only" if category == FileCategory.base else "unsupported"
            remote.processing_error = None
            await self.session.commit()
            return "processed"
        try:
            result = parser.parse(content, path)
            remote.parser_name = result.parser_name
            remote.parser_version = result.parser_version
            pending_events: list[dict[str, Any]] = []
            if category == FileCategory.character:
                pending_events = await self._ingest_characters(server_id, result.entities, digest, modified, observed)
            elif category == FileCategory.character_nowipe:
                await self._ingest_permanent_characters(server_id, result.entities, digest, modified, observed)
            elif category == FileCategory.vehicle:
                pending_events = await self._ingest_vehicles(server_id, result.entities, digest, modified, observed)
            elif category == FileCategory.storage:
                pending_events = await self._ingest_storages(server_id, result.entities, digest, modified, observed)
            elif category == FileCategory.deathlog:
                pending_events = await self._ingest_deaths(server_id, result.entities, modified)
            remote.status = "processed"
            remote.processing_error = None
            remote.last_processed_at = observed
            await self.session.commit()
            for domain_event in pending_events:
                await event_service.publish_after_commit(server_id=server_id, source="ingestion", **domain_event)
            return "processed"
        except (ParseError, ValueError, TypeError) as exc:
            await self.session.rollback()
            remote = await self.session.scalar(select(RemoteFile).where(RemoteFile.server_id == server_id, RemoteFile.remote_path == path))
            if remote is None:
                remote = RemoteFile(server_id=server_id, remote_path=path, category=category, remote_size=remote_size, content_hash=digest)
                self.session.add(remote)
            remote.category = category
            remote.remote_size = remote_size
            remote.remote_modified_at = modified
            remote.content_hash = digest
            remote.last_seen_at = observed
            remote.last_downloaded_at = observed
            remote.status = "error"
            remote.processing_error = str(exc)
            remote.retry_count = (remote.retry_count or 0) + 1
            await self.session.commit()
            logger.warning("file parsing failed", extra={"remote_path": path, "error": str(exc)})
            return "failed"

    async def _ingest_characters(self, server_id: uuid.UUID, entities: list[dict[str, Any]], digest: str, modified: datetime, observed: datetime) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for entity in entities:
            current = await self.session.scalar(select(CharacterCurrent).where(CharacterCurrent.server_id == server_id, CharacterCurrent.player_id == entity["player_id"]))
            is_new = current is None
            if current is None:
                current = CharacterCurrent(server_id=server_id, player_id=entity["player_id"])
                self.session.add(current)
            changed_position = _position_changed(current, entity, self.settings.position_tolerance_unreal)
            for key in ("login", "map_name", "pos_x", "pos_y", "pos_z", "rot_yaw", "health", "inventory", "raw_data"):
                setattr(current, key, entity[key])
            current.source_modified_at = modified
            current.observed_at = observed
            exists = await self.session.scalar(select(CharacterSnapshot.id).where(CharacterSnapshot.server_id == server_id, CharacterSnapshot.player_id == entity["player_id"], CharacterSnapshot.content_hash == digest))
            if not exists:
                self.session.add(CharacterSnapshot(server_id=server_id, player_id=entity["player_id"], content_hash=digest, data=entity, observed_at=observed))
            if changed_position and entity["pos_x"] is not None and entity["pos_y"] is not None:
                self.session.add(CharacterPositionHistory(server_id=server_id, player_id=entity["player_id"], pos_x=entity["pos_x"], pos_y=entity["pos_y"], pos_z=entity["pos_z"], observed_at=observed))
            base_data = {"player_id": entity["player_id"], "name": entity["login"], "observed_at": observed.isoformat()}
            events.append({"event": "character.created" if is_new else "character.updated", "entity_type": "character", "entity_id": entity["player_id"], "occurred_at": observed, "data": base_data})
            if changed_position and entity["pos_x"] is not None and entity["pos_y"] is not None:
                events.append({"event": "character.position.updated", "entity_type": "character", "entity_id": entity["player_id"], "occurred_at": observed, "data": {**base_data, **MapService().position(entity["pos_x"], entity["pos_y"], entity["pos_z"]), "position_freshness": "fresh"}})
        return events

    async def _ingest_vehicles(self, server_id: uuid.UUID, entities: list[dict[str, Any]], digest: str, modified: datetime, observed: datetime) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entity in entities:
            seen.add(entity["vehicle_uid"])
            current = await self.session.scalar(select(VehicleCurrent).where(VehicleCurrent.server_id == server_id, VehicleCurrent.vehicle_uid == entity["vehicle_uid"]))
            is_new = current is None
            if current is None:
                current = VehicleCurrent(server_id=server_id, vehicle_uid=entity["vehicle_uid"])
                self.session.add(current)
            changed_position = _position_changed(current, entity, self.settings.position_tolerance_unreal)
            for key in ("actor_id", "display_name", "pos_x", "pos_y", "pos_z", "rotation", "fuel", "durability", "lock_state", "inventory", "raw_data"):
                setattr(current, key, entity[key])
            current.metadata_json = entity["metadata"]
            current.active = True
            current.missing_since = None
            current.source_modified_at = modified
            current.observed_at = observed
            exists = await self.session.scalar(select(VehicleSnapshot.id).where(VehicleSnapshot.server_id == server_id, VehicleSnapshot.vehicle_uid == entity["vehicle_uid"], VehicleSnapshot.content_hash == digest))
            if not exists:
                self.session.add(VehicleSnapshot(server_id=server_id, vehicle_uid=entity["vehicle_uid"], content_hash=digest, data=entity, observed_at=observed))
            if changed_position and entity["pos_x"] is not None and entity["pos_y"] is not None:
                self.session.add(VehiclePositionHistory(server_id=server_id, vehicle_uid=entity["vehicle_uid"], pos_x=entity["pos_x"], pos_y=entity["pos_y"], pos_z=entity["pos_z"], observed_at=observed))
            base_data = {"vehicle_uid": entity["vehicle_uid"], "display_name": entity["display_name"], "active": True, "observed_at": observed.isoformat()}
            events.append({"event": "vehicle.created" if is_new else "vehicle.updated", "entity_type": "vehicle", "entity_id": entity["vehicle_uid"], "occurred_at": observed, "data": base_data})
            if changed_position and entity["pos_x"] is not None and entity["pos_y"] is not None:
                events.append({"event": "vehicle.position.updated", "entity_type": "vehicle", "entity_id": entity["vehicle_uid"], "occurred_at": observed, "data": {**base_data, **MapService().position(entity["pos_x"], entity["pos_y"], entity["pos_z"])}})
        previous = (await self.session.scalars(select(VehicleCurrent).where(VehicleCurrent.server_id == server_id, VehicleCurrent.active.is_(True)))).all()
        for vehicle in previous:
            if vehicle.vehicle_uid not in seen:
                if vehicle.missing_since is None:
                    vehicle.missing_since = observed
                else:
                    vehicle.active = False
                    events.append({"event": "vehicle.disappeared", "entity_type": "vehicle", "entity_id": vehicle.vehicle_uid, "occurred_at": observed, "data": {"active": False, "missing_since": vehicle.missing_since.isoformat()}})
        return events

    async def _ingest_permanent_characters(self, server_id: uuid.UUID, entities: list[dict[str, Any]], digest: str, modified: datetime, observed: datetime) -> None:
        for entity in entities:
            current = await self.session.scalar(select(CharacterPermanentData).where(
                CharacterPermanentData.server_id == server_id,
                CharacterPermanentData.player_id == entity["player_id"],
            ))
            data = {**entity, "content_hash": digest, "source_modified_at": modified.isoformat()}
            if current is None:
                current = CharacterPermanentData(server_id=server_id, player_id=entity["player_id"], data=data)
                self.session.add(current)
            else:
                current.data = data
                current.observed_at = observed

    async def _ingest_storages(self, server_id: uuid.UUID, entities: list[dict[str, Any]], digest: str, modified: datetime, observed: datetime) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for entity in entities:
            storage_id = entity["storage_id"]
            current = await self.session.scalar(select(StorageCurrent).where(
                StorageCurrent.server_id == server_id,
                StorageCurrent.data["storage_id"].as_string() == storage_id,
            ))
            data = {**entity, "content_hash": digest, "source_modified_at": modified.isoformat()}
            if current is None:
                current = StorageCurrent(server_id=server_id, data=data, observed_at=observed)
                self.session.add(current)
            else:
                current.data = data
                current.observed_at = observed
            snapshot_exists = await self.session.scalar(select(StorageSnapshot.id).where(
                StorageSnapshot.server_id == server_id,
                StorageSnapshot.data["storage_id"].as_string() == storage_id,
                StorageSnapshot.data["content_hash"].as_string() == digest,
            ))
            if not snapshot_exists:
                self.session.add(StorageSnapshot(server_id=server_id, data=data, observed_at=observed))
            events.append({"event": "storage.updated", "entity_type": "storage", "entity_id": storage_id, "occurred_at": observed, "data": {"storage_id": storage_id, "player_id": entity.get("player_id"), "item_count": entity.get("item_count"), "grid": entity.get("grid"), "observed_at": observed.isoformat()}})
        return events

    async def _ingest_deaths(self, server_id: uuid.UUID, entities: list[dict[str, Any]], modified: datetime) -> list[dict[str, Any]]:
        new_rows: list[DeathEvent] = []
        fingerprints = [entity["fingerprint"] for entity in entities]
        existing = set((await self.session.scalars(select(DeathEvent.fingerprint).where(
            DeathEvent.server_id == server_id,
            DeathEvent.fingerprint.in_(fingerprints),
        ))).all()) if fingerprints else set()
        for entity in entities:
            if entity["fingerprint"] in existing:
                continue
            data = dict(entity)
            data.pop("killer_name_normalized", None)
            data.pop("victim_name_normalized", None)
            data["server_id"] = server_id
            data["source_modified_at"] = modified
            death = DeathEvent(**data)
            self.session.add(death)
            new_rows.append(death)
            existing.add(entity["fingerprint"])
        await self.session.flush()
        events: list[dict[str, Any]] = []
        for death in new_rows:
            if death.is_player_kill:
                payload = {"killer": {"id": death.killer_id, "name": death.killer_name}, "victim": {"id": death.victim_id, "name": death.victim_name}, "weapon": death.weapon_name, "distance_meters": death.distance_meters, "is_player_kill": True, "event_time": death.event_time.isoformat()}
                if death.map_x is not None and death.map_y is not None:
                    payload["map_position"] = {"x": death.map_x, "y": death.map_y, "grid": death.grid}
                name = "kill.created"
            else:
                payload = {"event_type": death.event_type, "victim_id": death.victim_id, "victim_name": death.victim_name, "killer_type": death.killer_type, "cause": death.cause, "event_time": death.event_time.isoformat()}
                name = "death.created"
            events.append({"event": name, "entity_type": "kill" if death.is_player_kill else "death", "entity_id": str(death.id), "occurred_at": death.event_time, "data": payload})
        return events


def _position_changed(current: Any, entity: dict[str, Any], tolerance: float) -> bool:
    if current.pos_x is None or current.pos_y is None:
        return entity.get("pos_x") is not None and entity.get("pos_y") is not None
    for key in ("pos_x", "pos_y", "pos_z"):
        old, new = getattr(current, key, None), entity.get(key)
        if old is not None and new is not None and abs(old - new) > tolerance:
            return True
    return False
