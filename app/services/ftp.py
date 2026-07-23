import asyncio
import hashlib
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any

import aioftp
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.db.models import CharacterCurrent, FTPConnection, FileCategory, RemoteFile, SyncRun
from app.db.session import SessionLocal
from app.services.ingestion import ZipImporter, categorize_path
from app.services.event_service import event_service
from app.services.map_service import MapService

logger = logging.getLogger(__name__)


class FTPIntegrationError(Exception):
    def __init__(self, code: str, safe_message: str):
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


@dataclass(frozen=True)
class RemoteEntry:
    path: str
    size: int
    modified_at: datetime | None
    is_dir: bool = False


def _parse_modified(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _entry(path: Any, info: dict[str, Any]) -> RemoteEntry:
    return RemoteEntry(
        path="/" + str(path).replace("\\", "/").lstrip("/"),
        size=int(info.get("size", 0)),
        modified_at=_parse_modified(info.get("modify")),
        is_dir=info.get("type") == "dir",
    )


class ReadOnlyFTPClient:
    """Small read-only aioftp adapter; it intentionally exposes no mutation methods."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.client: aioftp.Client | None = None

    async def __aenter__(self):
        self.client = aioftp.Client(
            socket_timeout=self.settings.ftp_operation_timeout_seconds,
            connection_timeout=self.settings.ftp_connection_timeout_seconds,
            ssl=self.settings.ftp_use_tls,
            passive_commands=("epsv", "pasv"),
        )
        try:
            await self.client.connect(self.settings.ftp_host, self.settings.ftp_port)
            await self.client.login(
                self.settings.ftp_username,
                self.settings.ftp_password.get_secret_value(),
            )
            return self
        except Exception as exc:
            await self.close()
            name = type(exc).__name__.lower()
            code = "FTP_AUTH_FAILED" if "status" in name or "login" in str(exc).lower() else "FTP_CONNECTION_FAILED"
            message = "Falha ao autenticar no FTP." if code == "FTP_AUTH_FAILED" else "Falha ao conectar ao FTP."
            raise FTPIntegrationError(code, message) from None

    async def __aexit__(self, *_: Any):
        await self.close()

    async def close(self):
        if self.client is not None:
            try:
                await self.client.quit()
            except Exception:
                pass
            self.client = None

    async def list_dir(self, path: str) -> list[RemoteEntry]:
        assert self.client is not None
        try:
            return [_entry(item, info) async for item, info in self.client.list(path)]
        except Exception as exc:
            raise FTPIntegrationError("FTP_LIST_FAILED", "Não foi possível listar o diretório FTP.") from None

    async def stat(self, path: str) -> RemoteEntry:
        assert self.client is not None
        try:
            return _entry(path, await self.client.stat(path))
        except Exception:
            raise FTPIntegrationError("FTP_STAT_FAILED", "Não foi possível consultar o arquivo FTP.") from None

    async def download(self, remote_path: str, local_path: Path):
        assert self.client is not None
        try:
            await self.client.download(remote_path, local_path, write_into=True)
        except Exception:
            raise FTPIntegrationError("FTP_DOWNLOAD_FAILED", "Não foi possível baixar o arquivo FTP.") from None


async def discover_tree(client: ReadOnlyFTPClient, root: str, max_depth: int) -> tuple[list[RemoteEntry], dict[str, str]]:
    queue: list[tuple[str, int]] = [(root or "/", 0)]
    entries: list[RemoteEntry] = []
    paths: dict[str, str] = {}
    wanted = {
        "characters_path": lambda n: n.startswith("characters") and n != "characters_nowipe",
        "characters_nowipe_path": lambda n: n == "characters_nowipe",
        "vehicles_path": lambda n: n.startswith("new_vehicles"),
        "storages_path": lambda n: n.startswith("storages"),
        "deathlogs_path": lambda n: n == "deathlogs",
        "config_path": lambda n: n == "linuxserver",
        "bases_path": lambda n: n == "bases",
        "logs_path": lambda n: n == "logs",
    }
    while queue:
        current, depth = queue.pop(0)
        children = await client.list_dir(current)
        entries.extend(children)
        for child in children:
            if not child.is_dir:
                continue
            name = PurePosixPath(child.path).name.lower()
            for key, predicate in wanted.items():
                if key not in paths and predicate(name):
                    paths[key] = child.path
            if name.startswith("actual"):
                paths.setdefault("deadside_root", child.path)
            if depth < max_depth:
                queue.append((child.path, depth + 1))
    return entries, paths


def _monitored(entry: RemoteEntry) -> bool:
    if entry.is_dir:
        return False
    category = categorize_path(entry.path)
    name = PurePosixPath(entry.path.lower()).name
    return category != FileCategory.unknown or name in {"admin.conf", "server.info"}


def remote_changed(known: RemoteFile | None, current: RemoteEntry) -> bool:
    return not (
        known
        and known.remote_size == current.size
        and known.remote_modified_at == current.modified_at
        and known.status in {"processed", "metadata_only", "unsupported"}
    )


def stable_metadata(before: RemoteEntry, after: RemoteEntry) -> bool:
    return before.size == after.size and before.modified_at == after.modified_at


def parse_online_logins(content: bytes) -> set[str]:
    """Build current session state from safe join/logout markers in Deadside.log."""
    online: set[str] = set()
    for line in content.decode("utf-8", errors="replace").splitlines():
        joined = re.search(r"Join succeeded:\s*(.+?)\s*$", line)
        if joined:
            online.add(joined.group(1))
            continue
        logged_out = re.search(r"Player\s+(?:ltEOS\s+)?(.+?)\s+has logged out\b", line)
        if logged_out:
            online.discard(logged_out.group(1))
    return online


@dataclass
class SyncStatus:
    running: bool = False
    connected: bool = False
    last_check_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error_message: str | None = None
    files_scanned: int = 0
    files_changed: int = 0
    files_processed: int = 0
    files_failed: int = 0
    current_cycle_duration_ms: int = 0


class FTPSyncManager:
    def __init__(self):
        self.settings = get_settings()
        self._locks: dict[uuid.UUID, asyncio.Lock] = {}
        self._tasks: dict[uuid.UUID, asyncio.Task] = {}
        self._live_tasks: dict[uuid.UUID, asyncio.Task] = {}
        self._online_logins: dict[uuid.UUID, set[str]] = {}
        self._online_player_ids: dict[uuid.UUID, set[str]] = {}
        self._statuses: dict[uuid.UUID, SyncStatus] = {}

    def status(self, server_id: uuid.UUID) -> dict[str, Any]:
        state = self._statuses.setdefault(server_id, SyncStatus())
        result = asdict(state)
        result["state"] = "running" if state.running else "stopped"
        result["connection"] = "connected" if state.connected else "disconnected"
        result["live_position_monitor"] = "running" if server_id in self._live_tasks else "stopped"
        result["live_position_interval_seconds"] = self.settings.ftp_live_position_interval_seconds
        result["online_players"] = len(self._online_player_ids.get(server_id, set()))
        return result

    def online_player_ids(self, server_id: uuid.UUID) -> set[str]:
        return set(self._online_player_ids.get(server_id, set()))

    async def test_connection(self) -> dict[str, Any]:
        started = time.perf_counter()
        async with ReadOnlyFTPClient(self.settings) as client:
            entries = await client.list_dir(self.settings.ftp_root_path)
        octets = self.settings.ftp_host.split(".")
        masked = ".".join(octets[:2] + ["xxx", "xxx"]) if len(octets) == 4 else "***"
        return {
            "success": True, "protocol": self.settings.ftp_protocol, "host_masked": masked,
            "port": self.settings.ftp_port, "authenticated": True,
            "passive_mode": self.settings.ftp_passive_mode, "root_readable": True,
            "entries_found": len(entries), "latency_ms": round((time.perf_counter() - started) * 1000),
            "tested_at": datetime.now(UTC),
        }

    async def discover(self, server_id: uuid.UUID) -> dict[str, Any]:
        async with ReadOnlyFTPClient(self.settings) as client:
            entries, paths = await discover_tree(client, self.settings.ftp_root_path, self.settings.ftp_discovery_max_depth)
        async with SessionLocal() as session:
            connection = await session.scalar(select(FTPConnection).where(FTPConnection.server_id == server_id))
            if connection is None:
                connection = FTPConnection(server_id=server_id)
                session.add(connection)
            connection.protocol = self.settings.ftp_protocol
            connection.host = self.settings.ftp_host
            connection.port = self.settings.ftp_port
            connection.username = self.settings.ftp_username
            connection.encrypted_password = None
            connection.root_path = self.settings.ftp_root_path
            connection.path_patterns = paths
            await session.commit()
        return {"paths": paths, "entries_scanned": len(entries), "files_monitored": sum(_monitored(x) for x in entries)}

    async def run_once(self, server_id: uuid.UUID, trigger: str = "manual") -> dict[str, Any]:
        lock = self._locks.setdefault(server_id, asyncio.Lock())
        if lock.locked():
            return {"status": "already_running", **self.status(server_id)}
        async with lock:
            state = self._statuses.setdefault(server_id, SyncStatus())
            state.running = True
            state.last_check_at = datetime.now(UTC)
            started = time.perf_counter()
            counts = {"scanned": 0, "changed": 0, "processed": 0, "failed": 0, "skipped": 0}
            async with SessionLocal() as session:
                run = SyncRun(server_id=server_id, status="running")
                session.add(run)
                await session.commit()
                await event_service.publish_after_commit(event="sync.started", server_id=server_id, entity_type="sync", entity_id=str(run.id), occurred_at=datetime.now(UTC), source="ftp_sync", data={"sync_run_id": str(run.id), "trigger": trigger, "started_at": datetime.now(UTC).isoformat()})
                was_connected = state.connected
                publish_disconnected = False
                try:
                    async with ReadOnlyFTPClient(self.settings) as client:
                        state.connected = True
                        if not was_connected:
                            await event_service.publish_after_commit(event="ftp.connected", server_id=server_id, source="ftp_sync", data={"connected_at": datetime.now(UTC).isoformat()})
                        entries, _ = await discover_tree(client, self.settings.ftp_root_path, self.settings.ftp_discovery_max_depth)
                        files = [
                            x for x in entries
                            if _monitored(x)
                            and not (trigger == "polling" and categorize_path(x.path) == FileCategory.character)
                        ][:self.settings.ftp_max_files_per_cycle]
                        counts["scanned"] = len(files)
                        importer = ZipImporter(session)
                        with TemporaryDirectory(prefix="deadside-ftp-") as temp_dir:
                            for index, remote in enumerate(files):
                                known = await session.scalar(select(RemoteFile).where(RemoteFile.server_id == server_id, RemoteFile.remote_path == remote.path))
                                if not remote_changed(known, remote):
                                    counts["skipped"] += 1
                                    continue
                                counts["changed"] += 1
                                if remote.size > self.settings.ftp_max_file_size_mb * 1024 * 1024:
                                    counts["failed"] += 1
                                    logger.warning("FTP file exceeds configured size limit", extra={"remote_path": remote.path})
                                    continue
                                await asyncio.sleep(self.settings.ftp_stability_delay_seconds)
                                stable = await client.stat(remote.path)
                                if not stable_metadata(remote, stable):
                                    counts["skipped"] += 1
                                    continue
                                local = Path(temp_dir) / f"{index}.download"
                                await client.download(remote.path, local)
                                content = local.read_bytes()
                                if len(content) != remote.size:
                                    counts["failed"] += 1
                                    continue
                                outcome = await importer.process_content(server_id, remote.path, content, remote.size, remote.modified_at)
                                counts[outcome] += 1
                    state.connected = True
                    state.last_success_at = datetime.now(UTC)
                    state.last_error_message = None
                    run.status = "completed"
                except FTPIntegrationError as exc:
                    publish_disconnected = state.connected or was_connected
                    state.connected = False
                    state.last_error_at = datetime.now(UTC)
                    state.last_error_message = exc.safe_message
                    run.status = "failed"
                    run.error = exc.safe_message
                    raise
                finally:
                    elapsed = round((time.perf_counter() - started) * 1000)
                    state.files_scanned, state.files_changed = counts["scanned"], counts["changed"]
                    state.files_processed, state.files_failed = counts["processed"], counts["failed"]
                    state.current_cycle_duration_ms = elapsed
                    state.running = server_id in self._tasks
                    run.files_seen, run.files_processed, run.files_failed = counts["scanned"], counts["processed"], counts["failed"]
                    run.finished_at = datetime.now(UTC)
                    await session.commit()
                    await event_service.publish_after_commit(event="sync.progress", server_id=server_id, entity_type="sync", entity_id=str(run.id), source="ftp_sync", data={"sync_run_id": str(run.id), "files_scanned": counts["scanned"], "files_changed": counts["changed"], "files_processed": counts["processed"], "files_failed": counts["failed"]})
                    if run.status == "completed":
                        await event_service.publish_after_commit(event="sync.completed", server_id=server_id, entity_type="sync", entity_id=str(run.id), source="ftp_sync", data={"sync_run_id": str(run.id), "duration_ms": elapsed, "files_scanned": counts["scanned"], "files_changed": counts["changed"], "files_processed": counts["processed"], "files_failed": counts["failed"], "completed_at": datetime.now(UTC).isoformat()})
                    else:
                        if publish_disconnected:
                            await event_service.publish_after_commit(event="ftp.disconnected", server_id=server_id, source="ftp_sync", data={"disconnected_at": datetime.now(UTC).isoformat()})
                        await event_service.publish_after_commit(event="sync.failed", server_id=server_id, entity_type="sync", entity_id=str(run.id), source="ftp_sync", data={"sync_run_id": str(run.id), "error_code": "FTP_SYNC_FAILED", "message": run.error or "Falha de sincronização.", "failed_at": datetime.now(UTC).isoformat()})
            return {"status": "completed", **counts, "duration_ms": state.current_cycle_duration_ms}

    async def _poll(self, server_id: uuid.UUID):
        try:
            while True:
                for attempt in range(self.settings.ftp_max_retries):
                    try:
                        await self.run_once(server_id, trigger="polling")
                        break
                    except FTPIntegrationError:
                        await asyncio.sleep(self.settings.ftp_retry_base_seconds * (2 ** attempt))
                await asyncio.sleep(self.settings.ftp_poll_interval_seconds)
        except asyncio.CancelledError:
            raise
        finally:
            self._tasks.pop(server_id, None)
            self._statuses.setdefault(server_id, SyncStatus()).running = False

    async def _character_directories(self, server_id: uuid.UUID, client: ReadOnlyFTPClient) -> list[str]:
        async with SessionLocal() as session:
            connection = await session.scalar(select(FTPConnection).where(FTPConnection.server_id == server_id))
            root = (connection.path_patterns or {}).get("characters_path") if connection else None
        if not root:
            _, paths = await discover_tree(client, self.settings.ftp_root_path, self.settings.ftp_discovery_max_depth)
            root = paths.get("characters_path")
        if not root:
            raise FTPIntegrationError("FTP_CHARACTERS_NOT_FOUND", "Diretório de personagens não encontrado no FTP.")
        children = await client.list_dir(root)
        worlds = [entry.path for entry in children if entry.is_dir and PurePosixPath(entry.path).name.lower().startswith("world_")]
        return worlds or [root]

    async def _current_log_path(self, server_id: uuid.UUID, client: ReadOnlyFTPClient) -> str:
        async with SessionLocal() as session:
            connection = await session.scalar(select(FTPConnection).where(FTPConnection.server_id == server_id))
            root = (connection.path_patterns or {}).get("logs_path") if connection else None
        root = root or "/Deadside/Saved/Logs"
        children = await client.list_dir(root)
        current = next(
            (entry.path for entry in children if not entry.is_dir and PurePosixPath(entry.path).name.casefold() == "deadside.log"),
            None,
        )
        if not current:
            raise FTPIntegrationError("FTP_CURRENT_LOG_NOT_FOUND", "Log atual do servidor não encontrado no FTP.")
        return current

    async def _download_bytes(self, client: ReadOnlyFTPClient, remote_path: str, prefix: str) -> bytes:
        with TemporaryDirectory(prefix=prefix) as temp_dir:
            local = Path(temp_dir) / "remote.download"
            await client.download(remote_path, local)
            return local.read_bytes()

    async def _refresh_online_player_ids(self, server_id: uuid.UUID):
        logins = self._online_logins.get(server_id, set())
        if not logins:
            self._online_player_ids[server_id] = set()
            return
        async with SessionLocal() as session:
            ids = (await session.scalars(
                select(CharacterCurrent.player_id).where(
                    CharacterCurrent.server_id == server_id,
                    CharacterCurrent.login.in_(logins),
                )
            )).all()
        self._online_player_ids[server_id] = set(ids)

    async def _refresh_online_sessions(self, server_id: uuid.UUID, client: ReadOnlyFTPClient, log_path: str):
        content = await self._download_bytes(client, log_path, "deadside-log-")
        self._online_logins[server_id] = parse_online_logins(content)
        await self._refresh_online_player_ids(server_id)

    async def _ingest_live_character(self, server_id: uuid.UUID, client: ReadOnlyFTPClient, remote: RemoteEntry):
        if remote.size > self.settings.ftp_max_file_size_mb * 1024 * 1024:
            return
        content = await self._download_bytes(client, remote.path, "deadside-live-")
        if len(content) > self.settings.ftp_max_file_size_mb * 1024 * 1024:
            return
        observed = datetime.now(UTC)
        player_id = PurePosixPath(remote.path).stem
        async with SessionLocal() as session:
            await ZipImporter(session).process_content(
                server_id, remote.path, content, len(content), remote.modified_at
            )
            character = await session.scalar(select(CharacterCurrent).where(
                CharacterCurrent.server_id == server_id,
                CharacterCurrent.player_id == player_id,
            ))
            if character is None or character.pos_x is None or character.pos_y is None:
                return
            character.observed_at = observed
            await session.commit()
            data = {
                "player_id": character.player_id,
                "name": character.login,
                "observed_at": observed.isoformat(),
                **MapService().position(character.pos_x, character.pos_y, character.pos_z),
                "position_freshness": "live",
            }
        await event_service.publish_after_commit(
            event="character.position.sampled",
            server_id=server_id,
            entity_type="character",
            entity_id=player_id,
            occurred_at=observed,
            source="ftp_live_monitor",
            data=data,
        )

    async def _live_positions(self, server_id: uuid.UUID):
        """Use server sessions to poll only online character saves every configured interval."""
        try:
            while True:
                try:
                    async with ReadOnlyFTPClient(self.settings) as client:
                        directories = await self._character_directories(server_id, client)
                        log_path = await self._current_log_path(server_id, client)
                        previous_log_metadata: tuple[int, datetime | None] | None = None
                        bootstrap_characters = True
                        character_files: list[RemoteEntry] = []
                        while True:
                            cycle_started = time.monotonic()
                            log_entry = await client.stat(log_path)
                            log_metadata = (log_entry.size, log_entry.modified_at)
                            if log_metadata != previous_log_metadata:
                                await self._refresh_online_sessions(server_id, client, log_path)
                                previous_log_metadata = log_metadata
                                entries: list[RemoteEntry] = []
                                for directory in directories:
                                    entries.extend(await client.list_dir(directory))
                                character_files = [
                                    entry for entry in entries
                                    if not entry.is_dir and categorize_path(entry.path) == FileCategory.character
                                ]
                            online_ids = self._online_player_ids.get(server_id, set())
                            targets = [remote for remote in character_files if PurePosixPath(remote.path).stem in online_ids]
                            if bootstrap_characters and self._online_logins.get(server_id) and not targets:
                                targets = character_files
                            for remote in targets:
                                await self._ingest_live_character(server_id, client, remote)
                            if bootstrap_characters:
                                bootstrap_characters = False
                                await self._refresh_online_player_ids(server_id)
                            elapsed = time.monotonic() - cycle_started
                            await asyncio.sleep(max(0, self.settings.ftp_live_position_interval_seconds - elapsed))
                except FTPIntegrationError as exc:
                    logger.warning("Live FTP position monitor reconnecting: %s", exc.safe_message)
                    await asyncio.sleep(self.settings.ftp_retry_base_seconds)
                except Exception:
                    logger.exception("Live FTP position monitor failed; reconnecting")
                    await asyncio.sleep(self.settings.ftp_retry_base_seconds)
        except asyncio.CancelledError:
            raise
        finally:
            self._live_tasks.pop(server_id, None)
            self._online_logins.pop(server_id, None)
            self._online_player_ids.pop(server_id, None)

    def start(self, server_id: uuid.UUID) -> dict[str, Any]:
        if server_id in self._tasks:
            return {"status": "already_running", **self.status(server_id)}
        self._statuses.setdefault(server_id, SyncStatus()).running = True
        self._tasks[server_id] = asyncio.create_task(self._poll(server_id), name=f"ftp-sync-{server_id}")
        self._live_tasks[server_id] = asyncio.create_task(self._live_positions(server_id), name=f"ftp-live-{server_id}")
        return {"status": "started", **self.status(server_id)}

    async def stop(self, server_id: uuid.UUID) -> dict[str, Any]:
        task = self._tasks.get(server_id)
        if task is None:
            return {"status": "already_stopped", **self.status(server_id)}
        task.cancel()
        live_task = self._live_tasks.get(server_id)
        if live_task is not None:
            live_task.cancel()
        await asyncio.gather(task, *([live_task] if live_task is not None else []), return_exceptions=True)
        return {"status": "stopped", **self.status(server_id)}

    async def shutdown(self):
        tasks = [*self._tasks.values(), *self._live_tasks.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


ftp_sync_manager = FTPSyncManager()
