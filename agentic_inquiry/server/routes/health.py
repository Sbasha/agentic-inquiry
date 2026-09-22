"""Health check endpoint."""

import os
import time

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health_check(request: Request) -> dict:
    """Server health check."""
    return {
        "status": "ok",
        "pid": os.getpid(),
        "port": request.url.port,
        "project_id": request.app.state.project_id,
        "uptime": time.time() - request.app.state.started_at,
        "cache": request.app.state.cache_manager.stats,
    }
