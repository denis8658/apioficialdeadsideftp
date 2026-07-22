import base64
import hashlib
import hmac
import json
import time

import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.core.logging import redact_sensitive_text
from app.websocket.auth import WebSocketAuthError, authenticate_websocket


def jwt(payload, secret="test-secret"):
    encode = lambda value: base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=").decode()
    header = encode({"alg": "HS256", "typ": "JWT"}); body = encode(payload)
    signature = base64.urlsafe_b64encode(hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{header}.{body}.{signature}"


@pytest.fixture(autouse=True)
def websocket_secret():
    settings = get_settings(); previous = settings.websocket_jwt_secret
    settings.websocket_jwt_secret = SecretStr("test-secret")
    yield
    settings.websocket_jwt_secret = previous


def claims(**overrides):
    value = {"sub": "user-1", "role": "SERVER_ADMIN", "server_ids": ["server-a"], "exp": time.time() + 300}
    value.update(overrides); return value


def test_authenticated_connection_claims_are_accepted():
    principal = authenticate_websocket(jwt(claims()), "server-a", "sync")
    assert principal.user_id == "user-1" and principal.role == "SERVER_ADMIN"


@pytest.mark.parametrize("token", [None, "invalid.token.value"])
def test_missing_or_invalid_token_is_rejected(token):
    with pytest.raises(WebSocketAuthError) as caught:
        authenticate_websocket(token, "server-a", "kills")
    assert caught.value.code == 4401


def test_expired_token_is_rejected():
    with pytest.raises(WebSocketAuthError) as caught:
        authenticate_websocket(jwt(claims(exp=time.time() - 1)), "server-a", "kills")
    assert caught.value.code == 4401


def test_access_to_other_server_is_rejected():
    with pytest.raises(WebSocketAuthError) as caught:
        authenticate_websocket(jwt(claims()), "server-b", "kills")
    assert caught.value.code == 4403


def test_public_role_can_only_access_public_kills_channel():
    token = jwt(claims(role="PUBLIC"))
    assert authenticate_websocket(token, "server-a", "kills").role == "PUBLIC"
    with pytest.raises(WebSocketAuthError) as caught:
        authenticate_websocket(token, "server-a", "map")
    assert caught.value.code == 4403


def test_tokens_and_passwords_are_redacted_from_logs():
    message = "GET /ws?token=visible&x=1 Authorization: Bearer jwt-value password=hunter2"
    cleaned = redact_sensitive_text(message)
    assert "visible" not in cleaned and "jwt-value" not in cleaned and "hunter2" not in cleaned
