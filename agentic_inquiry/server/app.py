"""ai Server Application Factory.

Creates a FastAPI app with dual surfaces:
- REST API at /api/v1/* (for hooks, CLI, plugin skills)
- MCP at /mcp (for AI clients like Gemini, Codex, OpenCode)
"""

import logging
import os
import time

from fastapi import FastAPI

from agentic_inquiry.server.cache import ServerCacheManager
from agentic_inquiry.server.session import SessionState
from agentic_inquiry.server.signals import SignalAnalyzer
from agentic_inquiry.server.versioning import GitVersionManager

logger = logging.getLogger("ai.server")

# Server defaults
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
SERVER_TITLE = "Agentic Inquiry Server"


async def create_app(
    config=None,
    project_id: str = "default",
    workspace: str | None = None,
) -> FastAPI:
    """Create the dual-surface FastAPI application.

    Args:
        config: ai Config object (loaded from config.yaml if None)
        project_id: Project identifier
        workspace: Workspace path for git operations
    """
    if config is None:
        from agentic_inquiry.config import Config
        config = Config.load()

    if workspace is None:
        workspace = os.getcwd()

    # Load daemon-specific config for signal/cache/version settings
    daemon_config = _load_daemon_config()

    # Create MCP server (initializes all core services)
    from agentic_inquiry.mcp.server import MCPServer
    mcp_server = MCPServer(config, project_id)
    await mcp_server.initialize()

    # Get ASGI app from FastMCP
    mcp_asgi = mcp_server.get_app().http_app(path="/mcp")

    # Create FastAPI app with MCP's lifespan
    app = FastAPI(
        title=SERVER_TITLE,
        version="1.0.0",
        lifespan=mcp_asgi.lifespan,
    )

    # Mount MCP ASGI app at /mcp (matches docs and http_app path)
    app.mount("/mcp", mcp_asgi)

    # Create server-specific managers
    signal_analyzer = SignalAnalyzer(daemon_config)
    session_state = SessionState(daemon_config)
    cache_manager = ServerCacheManager(daemon_config)
    version_manager = GitVersionManager(workspace=workspace, config=daemon_config)
    version_manager.update_last_commit()

    # Store shared state on app
    app.state.mcp_server = mcp_server
    app.state.services = mcp_server.services
    app.state.signal_analyzer = signal_analyzer
    app.state.session_state = session_state
    app.state.cache_manager = cache_manager
    app.state.version_manager = version_manager
    app.state.project_id = project_id
    app.state.workspace = workspace
    app.state.started_at = time.time()
    app.state.config = config
    app.state.daemon_config = daemon_config

    # Register auth middleware (ADR-001 Phase 1)
    from agentic_inquiry.server.middleware.auth import APIKeyAuthMiddleware
    auth_config = getattr(getattr(config, 'mcp', None), 'api', None)
    if auth_config and hasattr(auth_config, 'auth'):
        raw_auth = auth_config.auth
        app.add_middleware(APIKeyAuthMiddleware, auth_config=raw_auth)
        # auth field may be a dict or an object; use .get() with dict fallback
        auth_enabled = (
            raw_auth.get("enabled", False)
            if isinstance(raw_auth, dict)
            else getattr(raw_auth, "enabled", False)
        )
        logger.info("Auth middleware registered: enabled=%s", auth_enabled)

    # Register REST routes
    from agentic_inquiry.server.routes import health, search, memory, context, session, hooks, index
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(search.router, prefix="/api/v1", tags=["search"])
    app.include_router(memory.router, prefix="/api/v1", tags=["memory"])
    app.include_router(context.router, prefix="/api/v1", tags=["context"])
    app.include_router(session.router, prefix="/api/v1", tags=["session"])
    app.include_router(hooks.router, prefix="/api/v1", tags=["hooks"])
    app.include_router(index.router, prefix="/api/v1/index", tags=["index"])

    # Register search-specific validation error handler to provide
    # human-readable 422 messages when local_diff has the wrong schema.
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from agentic_inquiry.server.routes.search import _LOCAL_DIFF_EXAMPLE

    @app.exception_handler(RequestValidationError)
    async def _search_validation_error_handler(
        _req: object, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        is_local_diff_error = any(
            "local_diff" in str(e.get("loc", "")) for e in errors
        )
        if is_local_diff_error:
            return JSONResponse(
                status_code=422,
                content={
                    "error": "Invalid local_diff format",
                    "detail": _LOCAL_DIFF_EXAMPLE,
                    "code": "VALIDATION_ERROR",
                    "raw_errors": [
                        {"loc": list(e.get("loc", [])), "msg": e.get("msg", "")}
                        for e in errors
                    ],
                },
            )
        return JSONResponse(
            status_code=422,
            content={
                "error": "Request validation failed",
                "detail": str(exc),
                "code": "VALIDATION_ERROR",
            },
        )

    from fastapi.responses import RedirectResponse
    @app.get("/ui")
    async def ui_redirect():
        return RedirectResponse(url="/ui/")

    logger.info(
        "ai server created: project=%s, REST at /api/v1, MCP at /mcp, UI at /ui",
        project_id,
    )

    return app


def _load_daemon_config() -> dict:
    """Load daemon-specific config (signal weights, cache settings, etc.)."""
    import yaml

    # Check for daemon-defaults.yaml in extensions
    config_paths = [
        os.path.join(os.getcwd(), "extensions/claude/ai/config/daemon-defaults.yaml"),
        os.path.expanduser("~/.agentic-inquiry/daemon-defaults.yaml"),
    ]

    for path in config_paths:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = yaml.safe_load(f)
                return data.get("daemon", {})
            except Exception:
                logger.debug("Failed to load daemon config from %s", path)

    # Return defaults
    return {}
