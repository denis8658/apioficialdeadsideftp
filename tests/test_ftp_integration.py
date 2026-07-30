import asyncio
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.services.ftp import (
    FTPSyncManager,
    ReadOnlyFTPClient,
    RemoteEntry,
    discover_tree,
    parse_online_logins,
    remaining_interval,
    remote_changed,
    stable_metadata,
)


def ftp_settings(**overrides):
    values = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "ftp_host": "ftp.example.test",
        "ftp_port": 28221,
        "ftp_username": "reader",
        "ftp_password": "top-secret",
        "ftp_passive_mode": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_password_is_secret_string():
    settings = ftp_settings()
    assert isinstance(settings.ftp_password, SecretStr)


def test_default_incremental_refresh_target_is_half_a_second():
    settings = ftp_settings()
    assert settings.ftp_poll_interval_seconds == 0.5
    assert settings.ftp_full_sync_interval_seconds == 60
    assert settings.ftp_live_position_interval_seconds == 0.5
    assert settings.ftp_stability_delay_seconds == 0.1
    assert "top-secret" not in repr(settings)


def test_custom_port_and_passive_mode_are_configurable():
    settings = ftp_settings()
    assert settings.ftp_port == 28221
    assert settings.ftp_passive_mode is True


@pytest.mark.asyncio
async def test_client_uses_custom_port_and_credentials(monkeypatch):
    fake = SimpleNamespace(connect=AsyncMock(), login=AsyncMock(), quit=AsyncMock())
    monkeypatch.setattr("app.services.ftp.aioftp.Client", lambda **_: fake)
    async with ReadOnlyFTPClient(ftp_settings()):
        pass
    fake.connect.assert_awaited_once_with("ftp.example.test", 28221)
    fake.login.assert_awaited_once_with("reader", "top-secret")


@pytest.mark.asyncio
async def test_authentication_error_is_safe(monkeypatch):
    fake = SimpleNamespace(connect=AsyncMock(), login=AsyncMock(side_effect=RuntimeError("login refused top-secret")), quit=AsyncMock())
    monkeypatch.setattr("app.services.ftp.aioftp.Client", lambda **_: fake)
    with pytest.raises(Exception) as caught:
        async with ReadOnlyFTPClient(ftp_settings()):
            pass
    assert "top-secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_discovery_finds_expected_directories():
    client = SimpleNamespace(list_dir=AsyncMock(side_effect=[
        [RemoteEntry("/Deadside", 0, None, True)],
        [RemoteEntry("/Deadside/Saved", 0, None, True)],
        [RemoteEntry("/Deadside/Saved/actual1", 0, None, True), RemoteEntry("/Deadside/Saved/Logs", 0, None, True)],
        [RemoteEntry("/Deadside/Saved/actual1/characters1-9", 0, None, True)],
        [],
        [],
    ]))
    _, paths = await discover_tree(client, "/", 8)
    assert paths["deadside_root"].endswith("actual1")
    assert paths["characters_path"].endswith("characters1-9")
    assert paths["logs_path"].endswith("Logs")


@pytest.mark.asyncio
async def test_discovery_obeys_depth_limit():
    client = SimpleNamespace(list_dir=AsyncMock(return_value=[RemoteEntry("/next", 0, None, True)]))
    await discover_tree(client, "/", 1)
    assert client.list_dir.await_count == 2


def test_new_file_is_changed():
    assert remote_changed(None, RemoteEntry("/a.sav", 10, None))


def test_same_processed_metadata_is_not_changed():
    modified = datetime.now(UTC)
    known = SimpleNamespace(remote_size=10, remote_modified_at=modified, status="processed")
    assert not remote_changed(known, RemoteEntry("/a.sav", 10, modified))


def test_changed_size_is_detected():
    known = SimpleNamespace(remote_size=9, remote_modified_at=None, status="processed")
    assert remote_changed(known, RemoteEntry("/a.sav", 10, None))


def test_unstable_file_is_rejected():
    assert not stable_metadata(RemoteEntry("/a", 1, None), RemoteEntry("/a", 2, None))


def test_stable_file_is_accepted():
    modified = datetime.now(UTC)
    assert stable_metadata(RemoteEntry("/a", 1, modified), RemoteEntry("/a", 1, modified))


def test_online_logins_follow_join_and_logout_order():
    content = b"\n".join([
        b"[1]LogNet: Join succeeded: OLD_PLAYER",
        b"[2]LogNet: Join succeeded: ODIO_-ETERNO",
        b"[3]LogOnline: Player ltEOS OLD_PLAYER  has logged out by reason: LostConnection",
    ])
    assert parse_online_logins(content) == {"ODIO_-ETERNO"}


@pytest.mark.asyncio
async def test_online_session_changes_are_broadcast_immediately(monkeypatch):
    manager = FTPSyncManager()
    server_id = __import__("uuid").uuid4()
    download = AsyncMock(return_value=b"LogNet: Join succeeded: PLAYER")
    refresh_ids = AsyncMock()
    broadcast = AsyncMock()
    monkeypatch.setattr(manager, "_download_bytes", download)
    monkeypatch.setattr(manager, "_refresh_online_player_ids", refresh_ids)
    monkeypatch.setattr("app.services.ftp.connection_manager.broadcast_to_channel", broadcast)

    await manager._refresh_online_sessions(server_id, SimpleNamespace(), "/Deadside.log")
    assert {call.args[2]["event"] for call in broadcast.await_args_list} == {"player.online"}
    assert {call.args[1] for call in broadcast.await_args_list} == {"map", "events"}

    broadcast.reset_mock()
    download.return_value = b"LogOnline: Player ltEOS PLAYER has logged out by reason: Quit"
    await manager._refresh_online_sessions(server_id, SimpleNamespace(), "/Deadside.log")
    assert {call.args[2]["event"] for call in broadcast.await_args_list} == {"player.offline"}


@pytest.mark.asyncio
async def test_simultaneous_runs_return_already_running(monkeypatch):
    manager = FTPSyncManager()
    server_id = __import__("uuid").uuid4()
    lock = manager._locks.setdefault(server_id, asyncio.Lock())
    await lock.acquire()
    try:
        result = await manager.run_once(server_id)
    finally:
        lock.release()
    assert result["status"] == "already_running"


@pytest.mark.asyncio
async def test_start_is_idempotent(monkeypatch):
    manager = FTPSyncManager()
    server_id = __import__("uuid").uuid4()
    monkeypatch.setattr(manager, "_poll", AsyncMock())
    monkeypatch.setattr(manager, "_live_positions", AsyncMock())
    monkeypatch.setattr(manager, "_broadcast_live_positions", AsyncMock())
    first = manager.start(server_id)
    second = manager.start(server_id)
    assert first["status"] == "started"
    assert second["status"] == "already_running"
    manager._tasks[server_id].cancel()
    await asyncio.gather(manager._tasks[server_id], return_exceptions=True)
    manager._live_tasks[server_id].cancel()
    await asyncio.gather(manager._live_tasks[server_id], return_exceptions=True)
    manager._live_broadcast_tasks[server_id].cancel()
    await asyncio.gather(manager._live_broadcast_tasks[server_id], return_exceptions=True)


@pytest.mark.asyncio
async def test_live_websocket_snapshots_follow_configured_interval(monkeypatch):
    manager = FTPSyncManager()
    manager.settings.ftp_live_position_interval_seconds = 0.01
    server_id = __import__("uuid").uuid4()
    manager._online_player_ids[server_id] = {"1671389361"}
    manager._live_payloads[server_id] = {"1671389361": {"player_id": "1671389361", "map_position": {"grid": "H5"}}}
    broadcast = AsyncMock()
    monkeypatch.setattr("app.services.ftp.connection_manager.broadcast_to_channel", broadcast)
    task = asyncio.create_task(manager._broadcast_live_positions(server_id))
    await asyncio.sleep(0.035)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert broadcast.await_count >= 2
    assert all(call.args[1] == "map" for call in broadcast.await_args_list)
    assert all(call.args[2]["event"] == "character.position.live" for call in broadcast.await_args_list)


def test_general_poll_compensates_for_cycle_duration():
    assert remaining_interval(0.5, 100.0, 100.2) == pytest.approx(0.3)
    assert remaining_interval(0.5, 100.0, 100.8) == 0


@pytest.mark.asyncio
async def test_character_directories_use_discovered_world_folder(monkeypatch):
    manager = FTPSyncManager()
    server_id = __import__("uuid").uuid4()
    connection = SimpleNamespace(path_patterns={"characters_path": "/Deadside/Saved/actual1/characters1-9"})
    session = SimpleNamespace(
        __aenter__=AsyncMock(),
        __aexit__=AsyncMock(),
        scalar=AsyncMock(return_value=connection),
    )

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr("app.services.ftp.SessionLocal", SessionContext)
    client = SimpleNamespace(list_dir=AsyncMock(return_value=[
        RemoteEntry("/Deadside/Saved/actual1/characters1-9/world_0", 0, None, True)
    ]))
    directories = await manager._character_directories(server_id, client)
    assert directories == ["/Deadside/Saved/actual1/characters1-9/world_0"]


@pytest.mark.asyncio
async def test_realtime_directories_target_only_dynamic_world_folders(monkeypatch):
    manager = FTPSyncManager()
    server_id = __import__("uuid").uuid4()
    connection = SimpleNamespace(path_patterns={
        "storages_path": "/saved/storages",
        "vehicles_path": "/saved/vehicles",
        "deathlogs_path": "/saved/deathlogs",
    })
    session = SimpleNamespace(
        __aenter__=AsyncMock(),
        __aexit__=AsyncMock(),
        scalar=AsyncMock(return_value=connection),
    )

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr("app.services.ftp.SessionLocal", SessionContext)
    client = SimpleNamespace(list_dir=AsyncMock(side_effect=lambda root: [
        RemoteEntry(f"{root}/world_0", 0, None, True),
    ]))
    directories = await manager._realtime_directories(server_id, client)
    assert directories == [
        "/saved/storages/world_0",
        "/saved/vehicles/world_0",
        "/saved/deathlogs/world_0",
    ]


def test_secret_does_not_appear_in_logs(caplog):
    with caplog.at_level(logging.INFO):
        logging.getLogger("ftp-test").info("connection settings: %r", ftp_settings())
    assert "top-secret" not in caplog.text
