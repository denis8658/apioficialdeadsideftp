import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, JSON as JSONB, String, Text, UniqueConstraint, Uuid as UUID, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FileCategory(str, enum.Enum):
    character = "character"
    character_nowipe = "character_nowipe"
    vehicle = "vehicle"
    storage = "storage"
    deathlog = "deathlog"
    config = "config"
    log = "log"
    base = "base"
    unknown = "unknown"


class Server(Base):
    __tablename__ = "servers"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FTPConnection(Base):
    __tablename__ = "ftp_connections"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), unique=True, index=True)
    protocol: Mapped[str] = mapped_column(String(10), default="ftp")
    host: Mapped[str | None] = mapped_column(String(255))
    port: Mapped[int | None] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(255))
    encrypted_password: Mapped[str | None] = mapped_column(Text)
    root_path: Mapped[str | None] = mapped_column(Text)
    path_patterns: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    files_seen: Mapped[int] = mapped_column(Integer, default=0)
    files_processed: Mapped[int] = mapped_column(Integer, default=0)
    files_failed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class RemoteFile(Base):
    __tablename__ = "remote_files"
    __table_args__ = (UniqueConstraint("server_id", "remote_path"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    remote_path: Mapped[str] = mapped_column(Text, index=True)
    category: Mapped[FileCategory] = mapped_column(Enum(FileCategory, name="file_category"), index=True)
    remote_size: Mapped[int] = mapped_column(Integer)
    remote_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="discovered", index=True)
    parser_name: Mapped[str | None] = mapped_column(String(100))
    parser_version: Mapped[str | None] = mapped_column(String(30))
    processing_error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)


class CharacterCurrent(Base):
    __tablename__ = "characters_current"
    __table_args__ = (UniqueConstraint("server_id", "player_id"), Index("ix_character_coordinates", "server_id", "pos_x", "pos_y"))
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[str] = mapped_column(String(100), index=True)
    login: Mapped[str | None] = mapped_column(String(200))
    map_name: Mapped[str | None] = mapped_column(String(100))
    pos_x: Mapped[float | None] = mapped_column(Float)
    pos_y: Mapped[float | None] = mapped_column(Float)
    pos_z: Mapped[float | None] = mapped_column(Float)
    rot_yaw: Mapped[float | None] = mapped_column(Float)
    health: Mapped[float | None] = mapped_column(Float)
    inventory: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class CharacterPositionHistory(Base):
    __tablename__ = "character_position_history"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[str] = mapped_column(String(100), index=True)
    pos_x: Mapped[float] = mapped_column(Float)
    pos_y: Mapped[float] = mapped_column(Float)
    pos_z: Mapped[float | None] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class CharacterSnapshot(Base):
    __tablename__ = "character_snapshots"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[str] = mapped_column(String(100), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class CharacterPermanentData(Base):
    __tablename__ = "character_permanent_data"
    __table_args__ = (UniqueConstraint("server_id", "player_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[str] = mapped_column(String(100), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VehicleCurrent(Base):
    __tablename__ = "vehicles_current"
    __table_args__ = (UniqueConstraint("server_id", "vehicle_uid"), Index("ix_vehicle_coordinates", "server_id", "pos_x", "pos_y"))
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    vehicle_uid: Mapped[str] = mapped_column(String(100), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))
    pos_x: Mapped[float | None] = mapped_column(Float)
    pos_y: Mapped[float | None] = mapped_column(Float)
    pos_z: Mapped[float | None] = mapped_column(Float)
    rotation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    fuel: Mapped[float | None] = mapped_column(Float)
    durability: Mapped[float | None] = mapped_column(Float)
    lock_state: Mapped[int | None] = mapped_column(Integer)
    inventory: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    missing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class VehiclePositionHistory(Base):
    __tablename__ = "vehicle_position_history"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    vehicle_uid: Mapped[str] = mapped_column(String(100), index=True)
    pos_x: Mapped[float] = mapped_column(Float)
    pos_y: Mapped[float] = mapped_column(Float)
    pos_z: Mapped[float | None] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class VehicleSnapshot(Base):
    __tablename__ = "vehicle_snapshots"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    vehicle_uid: Mapped[str] = mapped_column(String(100), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


def _simple_snapshot(name: str, table: str):
    return type(name, (Base,), {"__tablename__": table, "id": mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4), "server_id": mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True), "data": mapped_column(JSONB, default=dict), "observed_at": mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)})


StorageCurrent = _simple_snapshot("StorageCurrent", "storages_current")
StorageSnapshot = _simple_snapshot("StorageSnapshot", "storage_snapshots")
class DeathEvent(Base):
    __tablename__ = "death_events"
    __table_args__ = (
        UniqueConstraint("server_id", "fingerprint", name="uq_death_event_fingerprint"),
        Index("ix_death_event_server_time", "server_id", "event_time"),
        Index("ix_death_event_server_type", "server_id", "event_type"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_type: Mapped[str] = mapped_column(String(30), index=True)
    victim_id: Mapped[str | None] = mapped_column(String(100), index=True)
    victim_name: Mapped[str | None] = mapped_column(String(200), index=True)
    victim_type: Mapped[str] = mapped_column(String(20))
    victim_platform: Mapped[str | None] = mapped_column(String(20))
    killer_id: Mapped[str | None] = mapped_column(String(100), index=True)
    killer_name: Mapped[str | None] = mapped_column(String(200), index=True)
    killer_type: Mapped[str] = mapped_column(String(20))
    killer_platform: Mapped[str | None] = mapped_column(String(20))
    weapon_id: Mapped[str | None] = mapped_column(String(200))
    weapon_name: Mapped[str | None] = mapped_column(String(200), index=True)
    cause: Mapped[str | None] = mapped_column(String(200))
    distance_meters: Mapped[float | None] = mapped_column(Float)
    is_player_kill: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_suicide: Mapped[bool] = mapped_column(Boolean, default=False)
    is_environmental: Mapped[bool] = mapped_column(Boolean, default=False)
    world_x: Mapped[float | None] = mapped_column(Float)
    world_y: Mapped[float | None] = mapped_column(Float)
    world_z: Mapped[float | None] = mapped_column(Float)
    map_x: Mapped[float | None] = mapped_column(Float)
    map_y: Mapped[float | None] = mapped_column(Float)
    grid: Mapped[str | None] = mapped_column(String(20), index=True)
    source_file: Mapped[str] = mapped_column(Text)
    source_line: Mapped[int] = mapped_column(Integer)
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    raw_data: Mapped[dict[str, Any]] = mapped_column("data", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column("observed_at", DateTime(timezone=True), server_default=func.now(), index=True)


class ServerEventSequence(Base):
    __tablename__ = "server_event_sequences"
    server_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DomainEvent(Base):
    __tablename__ = "domain_events"
    __table_args__ = (
        UniqueConstraint("server_id", "sequence", name="uq_domain_event_server_sequence"),
        Index("ix_domain_event_server_occurred", "server_id", "occurred_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_name: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(50), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(200), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str | None] = mapped_column(String(100))
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
ServerConfigSnapshot = _simple_snapshot("ServerConfigSnapshot", "server_config_snapshots")
LogEvent = _simple_snapshot("LogEvent", "log_events")
BaseFileSnapshot = _simple_snapshot("BaseFileSnapshot", "base_file_snapshots")
MapCalibration = _simple_snapshot("MapCalibration", "map_calibrations")
MapCalibrationPoint = _simple_snapshot("MapCalibrationPoint", "map_calibration_points")
