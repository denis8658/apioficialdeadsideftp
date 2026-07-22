import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings


class WebSocketAuthError(ValueError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WebSocketPrincipal:
    user_id: str
    role: str
    server_ids: frozenset[str]


def authenticate_websocket(token: str | None, server_id: str, channel: str, server_aliases: set[str] | None = None) -> WebSocketPrincipal:
    if not token:
        raise WebSocketAuthError(4401, "authentication required")
    secret = get_settings().websocket_jwt_secret.get_secret_value()
    if not secret:
        raise WebSocketAuthError(4401, "WebSocket authentication is not configured")
    payload = _decode_hs256(token, secret)
    if not isinstance(payload.get("exp"), (int, float)) or payload["exp"] <= time.time():
        raise WebSocketAuthError(4401, "token expired")
    user_id = payload.get("sub")
    role = str(payload.get("role", "PUBLIC")).upper()
    server_ids = frozenset(str(value) for value in payload.get("server_ids", []))
    if not user_id:
        raise WebSocketAuthError(4401, "invalid token subject")
    accepted_servers = {server_id, *(server_aliases or set())}
    if role != "SUPER_ADMIN" and not accepted_servers.intersection(server_ids):
        raise WebSocketAuthError(4403, "server access denied")
    allowed = {
        "kills": {"PUBLIC", "MAP_VIEWER", "MODERATOR", "SERVER_ADMIN", "SUPER_ADMIN"},
        "map": {"MAP_VIEWER", "MODERATOR", "SERVER_ADMIN", "SUPER_ADMIN"},
        "sync": {"SERVER_ADMIN", "SUPER_ADMIN"},
        "events": {"MAP_VIEWER", "MODERATOR", "SERVER_ADMIN", "SUPER_ADMIN"},
    }
    if role not in allowed[channel]:
        raise WebSocketAuthError(4403, "channel access denied")
    return WebSocketPrincipal(str(user_id), role, server_ids)


def _decode_hs256(token: str, secret: str) -> dict[str, Any]:
    try:
        header_part, payload_part, signature_part = token.split(".")
        header = json.loads(_decode_segment(header_part))
        payload = json.loads(_decode_segment(payload_part))
        expected = hmac.new(secret.encode(), f"{header_part}.{payload_part}".encode(), hashlib.sha256).digest()
        signature = _b64decode(signature_part)
    except Exception:
        raise WebSocketAuthError(4401, "invalid token") from None
    if header.get("alg") != "HS256" or not hmac.compare_digest(signature, expected):
        raise WebSocketAuthError(4401, "invalid token")
    return payload


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _decode_segment(value: str) -> str:
    return _b64decode(value).decode("utf-8")
