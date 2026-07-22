from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.cors import normalize_origin, normalize_origins
from app.core.logging import redact_sensitive_text
from app.core.middleware import RequestIdMiddleware, UnhandledExceptionMiddleware

ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]
ALLOWED_HEADERS = [
    "Authorization",
    "Content-Type",
    "Accept",
    "Origin",
    "X-Requested-With",
    "X-Request-ID",
    "X-CSRF-Token",
]
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def browser_app(*, credentials: bool = False) -> FastAPI:
    test_app = FastAPI(redirect_slashes=False)

    @test_app.api_route("/resource", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def resource(authorization: str | None = Header(None)):
        if authorization == "deny-401":
            raise HTTPException(401, "unauthorized")
        if authorization == "deny-403":
            raise HTTPException(403, "forbidden")
        return {"status": "ok"}

    @test_app.get("/status/{code}")
    async def status(code: int):
        if code == 500:
            raise RuntimeError("backend detail must not leak")
        return JSONResponse({"status": code}, status_code=code)

    test_app.add_middleware(UnhandledExceptionMiddleware)
    test_app.add_middleware(RequestIdMiddleware)
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=ORIGINS,
        allow_credentials=credentials,
        allow_methods=METHODS,
        allow_headers=ALLOWED_HEADERS,
        expose_headers=["X-Request-ID", "Content-Disposition", "X-Total-Count"],
        max_age=600,
    )
    return test_app


def preflight(client: TestClient, origin: str, method: str = "GET", headers: str = "authorization,content-type"):
    return client.options(
        "/resource",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )


@pytest.mark.parametrize("origin", ORIGINS)
def test_each_development_origin_is_allowed(origin):
    with TestClient(browser_app()) as client:
        response = preflight(client, origin)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_unlisted_origin_is_denied():
    with TestClient(browser_app()) as client:
        response = preflight(client, "https://evil.example")
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_csv_origins_are_trimmed_normalized_and_deduplicated():
    assert normalize_origins(" HTTPS://Painel.Example.com/ ,https://painel.example.com,,http://localhost:5173 ") == [
        "https://painel.example.com",
        "http://localhost:5173",
    ]


@pytest.mark.parametrize(
    "origin",
    [
        "https://painel.example.com/path",
        "https://painel.example.com?tenant=1",
        "https://painel.example.com#fragment",
        "javascript:alert(1)",
        "file://local/file",
        "https://user:password@painel.example.com",
    ],
)
def test_invalid_origins_are_rejected(origin):
    with pytest.raises(ValueError):
        normalize_origin(origin)


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE"])
def test_preflight_methods_authorization_content_type_and_custom_header(method):
    with TestClient(browser_app()) as client:
        response = preflight(
            client,
            "http://localhost:5173",
            method,
            "authorization,content-type,x-request-id,x-csrf-token",
        )
    assert response.status_code == 200
    assert response.status_code not in {307, 308, 401, 403}
    assert response.headers["access-control-max-age"] == "600"
    allowed = response.headers["access-control-allow-headers"].lower()
    for header in ("authorization", "content-type", "x-request-id", "x-csrf-token"):
        assert header in allowed


def test_unlisted_request_header_is_blocked():
    with TestClient(browser_app()) as client:
        response = preflight(client, "http://localhost:5173", headers="x-not-allowed")
    assert response.status_code == 400


@pytest.mark.parametrize("status", [200, 201, 204, 400, 401, 403, 404, 409, 422, 429, 500])
def test_success_and_error_responses_keep_cors(status):
    with TestClient(browser_app(), raise_server_exceptions=False) as client:
        response = client.get(f"/status/{status}", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == status
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers.get_list("access-control-allow-origin") == ["http://localhost:5173"]
    assert "origin" in response.headers["vary"].lower()
    assert "x-request-id" in response.headers["access-control-expose-headers"].lower()
    assert "content-disposition" in response.headers["access-control-expose-headers"].lower()
    if status == 500:
        assert response.json() == {"error": "internal server error", "status": 500}


def test_credentials_default_to_false_and_explicit_origins_support_true():
    with TestClient(browser_app(credentials=False)) as client:
        without_credentials = preflight(client, "http://localhost:3000")
    with TestClient(browser_app(credentials=True)) as client:
        with_credentials = preflight(client, "http://localhost:3000")
    assert "access-control-allow-credentials" not in without_credentials.headers
    assert with_credentials.headers["access-control-allow-credentials"] == "true"
    assert with_credentials.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_insecure_or_incomplete_settings_fail_at_startup():
    with pytest.raises(ValidationError, match="wildcard"):
        Settings(_env_file=None, cors_allowed_origins="*", cors_allow_credentials=True)
    with pytest.raises(ValidationError, match="OPTIONS"):
        Settings(_env_file=None, cors_allowed_methods="GET,POST")
    with pytest.raises(ValidationError, match="Authorization"):
        Settings(_env_file=None, cors_allowed_headers="Content-Type")
    with pytest.raises(ValidationError, match="explicit CORS"):
        Settings(
            _env_file=None,
            environment="production",
            cors_allowed_origins="",
            websocket_allowed_origins="https://panel.example.com",
        )
    with pytest.raises(ValidationError, match="explicit WebSocket"):
        Settings(
            _env_file=None,
            environment="production",
            cors_allowed_origins="https://panel.example.com",
            websocket_allowed_origins="*",
        )
    with pytest.raises(ValidationError, match="localhost"):
        Settings(_env_file=None, environment="production")
    with pytest.raises(ValidationError, match="regex"):
        Settings(
            _env_file=None,
            environment="production",
            cors_allowed_origins="https://panel.example.com",
            websocket_allowed_origins="https://panel.example.com",
            cors_allowed_origin_regex=".*",
        )
    with pytest.raises(ValidationError, match="path"):
        Settings(_env_file=None, cors_allowed_origins="https://panel.example.com/path")


def test_preflight_does_not_run_endpoint_auth_or_redirect():
    with TestClient(browser_app()) as client:
        response = preflight(client, "http://localhost:5173", method="GET")
        wrong_slash = client.options(
            "/resource/",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert response.status_code == 200
    assert wrong_slash.status_code not in {307, 308}


def test_forwarded_proxy_headers_do_not_change_origin_validation():
    with TestClient(browser_app()) as client:
        response = client.get(
            "/resource",
            headers={
                "Origin": "http://localhost:5173",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "api.example.com",
                "X-Forwarded-For": "203.0.113.10",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_tokens_and_cookies_are_redacted_from_logs():
    value = redact_sensitive_text(
        "GET /ws?token=jwt-value Authorization: Bearer secret Cookie: session=abc; csrf=def"
    )
    assert "jwt-value" not in value
    assert "Bearer secret" not in value
    assert "session=abc" not in value
    assert "csrf=def" not in value


def test_production_websocket_scheme_is_documented():
    readme = Path(__file__).parents[1].joinpath("README.md").read_text(encoding="utf-8")
    assert "wss://" in readme
