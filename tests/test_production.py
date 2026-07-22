import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.core.middleware import RateLimitMiddleware
from app.main import app


@pytest.mark.asyncio
async def test_root_health_and_security_headers():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.asyncio
async def test_validation_and_not_found_errors_are_structured():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        validation = await client.post(
            "/api/v1/servers", json={}, headers={"Origin": "http://localhost:5173"}
        )
        missing = await client.get(
            "/does-not-exist", headers={"Origin": "http://localhost:5173"}
        )

    assert validation.status_code == 422
    assert validation.json()["status"] == 422
    assert validation.json()["error"] == "validation error"
    assert validation.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert missing.status_code == 404
    assert missing.json() == {"error": "Not Found", "status": 404}
    assert missing.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.asyncio
async def test_cors_allows_configured_origin_only():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        allowed = await client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        denied = await client.options(
            "/health",
            headers={
                "Origin": "https://invalid.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


@pytest.mark.asyncio
async def test_rate_limit_protects_critical_mutations():
    inner = FastAPI()

    @inner.post("/api/v1/servers/test/sync/run")
    async def sync_run():
        return {"status": "ok"}

    settings = Settings(
        _env_file=None,
        rate_limit_requests=2,
        rate_limit_window_seconds=60,
    )
    limited = RateLimitMiddleware(inner, settings=settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=limited), base_url="http://test"
    ) as client:
        first = await client.post("/api/v1/servers/test/sync/run")
        second = await client.post("/api/v1/servers/test/sync/run")
        blocked = await client.post("/api/v1/servers/test/sync/run")

    assert first.status_code == second.status_code == 200
    assert blocked.status_code == 429
    assert blocked.json() == {"error": "rate limit exceeded", "status": 429}
    assert blocked.headers["retry-after"] == "60"


def test_port_uses_railway_environment_alias(monkeypatch):
    monkeypatch.setenv("PORT", "9123")
    settings = Settings(_env_file=None)
    assert settings.api_port == 9123


def test_railway_postgresql_url_uses_asyncpg_driver():
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:password@postgres.railway.internal:5432/railway",
    )

    assert settings.database_url == (
        "postgresql+asyncpg://user:password@postgres.railway.internal:5432/railway"
    )
