import asyncio
import logging
import re
import time
import uuid
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings

logger = logging.getLogger(__name__)


class UnhandledExceptionMiddleware:
    """Keep unexpected HTTP errors inside the CORS middleware response path."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            logger.exception(
                "Unhandled API error",
                extra={"path": scope.get("path", ""), "exception_type": type(exc).__name__},
            )
            response = JSONResponse({"error": "internal server error", "status": 500}, status_code=500)
            await response(scope, receive, send)


class RequestIdMiddleware(BaseHTTPMiddleware):
    _valid_request_id = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

    async def dispatch(self, request: Request, call_next) -> Response:
        supplied = request.headers.get("x-request-id", "")
        request_id = supplied if self._valid_request_id.fullmatch(supplied) else str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
        if self.settings.force_https or self.settings.environment.lower() == "production":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-process limiter for critical mutation endpoints; use Redis for multi-worker global limits."""
    critical_suffixes = ("/ftp/test", "/sync/run", "/sync/start", "/sync/stop")

    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings
        self._requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.settings.rate_limit_enabled or request.method != "POST" or not request.url.path.endswith(self.critical_suffixes):
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        key = (client, request.url.path)
        now = time.monotonic()
        cutoff = now - self.settings.rate_limit_window_seconds
        async with self._lock:
            bucket = self._requests[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.settings.rate_limit_requests:
                return JSONResponse({"error": "rate limit exceeded", "status": 429}, status_code=429, headers={"Retry-After": str(self.settings.rate_limit_window_seconds)})
            bucket.append(now)
        return await call_next(request)
