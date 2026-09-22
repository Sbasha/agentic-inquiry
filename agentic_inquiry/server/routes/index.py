"""Indexing status and management endpoints."""

import logging
from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger("ai.server.routes.index")

router = APIRouter()

@router.get("/status")
async def get_status(request: Request) -> dict:
    """Get indexing status and statistics."""
    services = request.app.state.services

    total_chunks = 0
    storage = services.get("storage")
    if storage is not None:
        try:
            total_chunks = await storage.count_chunks()
        except Exception:
            logger.exception("Failed to count chunks from storage")

    return {
        "total_docs": 0,
        "total_chunks": total_chunks,
        "indexed_at": "2026-03-12T00:00:00Z",
    }

@router.get("/documents")
async def list_documents(request: Request) -> dict:
    """List indexed documents."""
    # Dummy for now, ideally we query LanceDB for unique file_paths
    return {
        "documents": [
            {"name": "demo_doc.md", "status": "Indexed", "chunks": 10, "modified": "2026-03-12"},
        ]
    }


@router.get("/health")
async def get_health(request: Request) -> dict:
    """System health metrics for dashboards and monitoring."""
    services = request.app.state.services
    health_tracker = services.get("health_tracker")
    perf_monitor = services.get("perf_monitor")
    maintenance_task = services.get("maintenance_task")

    result: dict = {"status": "unknown"}

    if health_tracker:
        try:
            health = health_tracker.get_overall_health()
            result["status"] = health.status.value if hasattr(health, 'status') else str(health)
            result["components"] = {}
            if hasattr(health, 'components'):
                for name, component in health.components.items():
                    result["components"][name] = {
                        "status": component.status.value if hasattr(component, 'status') else str(component),
                        "latency_p50": getattr(component, 'latency_p50', None),
                        "latency_p95": getattr(component, 'latency_p95', None),
                        "error_rate": getattr(component, 'error_rate', None),
                    }
            result["is_active"] = health_tracker.is_active()
        except Exception as e:
            result["health_error"] = str(e)

    if perf_monitor:
        try:
            stats = perf_monitor.get_all_stats() if hasattr(perf_monitor, 'get_all_stats') else {}
            result["performance"] = stats
        except Exception:
            pass

    if maintenance_task is not None:
        result["maintenance_task"] = {"running": not maintenance_task.done()}

    return result
