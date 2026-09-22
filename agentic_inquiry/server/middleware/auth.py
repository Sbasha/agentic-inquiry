"""API key authentication middleware (ADR-001 Phase 1)."""

import logging
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("ai.server.middleware.auth")

EXEMPT_PATHS: frozenset[str] = frozenset({
    "/api/v1/health",
    "/health",
    "/docs",
    "/openapi.json",
})

EXEMPT_PREFIXES: tuple[str, ...] = (
    "/mcp",
    "/ui",
)


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth_config: dict) -> None:
        super().__init__(app)
        self.enabled: bool = auth_config.get("enabled", False)
        self.api_key: str | None = auth_config.get("api_key")

    async def dispatch(self, request: Request, call_next: Callable):
        if not self.enabled:
            request.state.request_id = str(uuid.uuid4())[:8]
            return await call_next(request)

        path = request.url.path
        if path in EXEMPT_PATHS or path.startswith(EXEMPT_PREFIXES):
            request.state.request_id = str(uuid.uuid4())[:8]
            return await call_next(request)

        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning(
                "AUTH_FAILED request_id=%s method=%s path=%s reason=missing_token",
                request_id, request.method, path,
            )
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized", "code": "AUTH_REQUIRED"},
            )

        token = auth_header[7:]
        if token != self.api_key:
            logger.warning(
                "AUTH_FAILED request_id=%s method=%s path=%s reason=invalid_token",
                request_id, request.method, path,
            )
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized", "code": "INVALID_TOKEN"},
            )

        ai_user = request.headers.get("x-ai-user", "anonymous")
        logger.info(
            "AUTH_OK request_id=%s method=%s path=%s user=%s",
            request_id, request.method, path, ai_user,
        )

        return await call_next(request)
