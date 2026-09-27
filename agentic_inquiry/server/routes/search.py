"""Search endpoint - hybrid search via shared service layer."""

import logging
import time
from contextlib import nullcontext

from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger("ai.server.routes.search")

router = APIRouter()


_LOCAL_DIFF_EXAMPLE = (
    "modified_files must be a list of objects with 'path' (string) "
    "and optional 'changed_lines' (list of integers) and 'status' (string). "
    'Example: {"modified_files": [{"path": "foo.py", "changed_lines": [10, 20]}]}'
)


class LocalDiffFile(BaseModel):
    """A single file's diff summary sent by the plugin."""

    path: str
    changed_lines: list[int] = []
    status: str = "modified"  # "modified", "added", "deleted"


class LocalDiff(BaseModel):
    """Structured local diff sent by the plugin (WS3)."""

    branch: str | None = None
    modified_files: list[LocalDiffFile] = []
    truncated: bool = False
    omitted_count: int = 0


class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    content_preference: str | None = None
    branch: str | None = None  # WS4: scope search to a specific branch
    local_diff: LocalDiff | None = None  # WS3: local change overlay


@router.post("/search")
async def search(request: Request, body: SearchRequest) -> dict:
    """Hybrid search across indexed content."""
    if not body.query.strip():
        return {"error": "Query cannot be empty", "code": "EMPTY_QUERY"}

    services = request.app.state.services
    search_service = services.get("search_service")
    if not search_service:
        return {"error": "Search service not available", "code": "SERVICE_UNAVAILABLE"}

    # Apply diff truncation before annotation (WS3)
    local_diff = body.local_diff
    if local_diff and local_diff.modified_files:
        config = getattr(request.app.state, "config", None)
        overlay_cfg = getattr(config, "overlay", None)
        max_per_file: int = getattr(overlay_cfg, "max_lines_per_file", 100)
        max_total: int = getattr(overlay_cfg, "max_lines_total", 500)
        overlay_enabled: bool = getattr(overlay_cfg, "enabled", True)

        if overlay_enabled:
            from agentic_inquiry.server.overlay.truncation import truncate_diff

            local_diff = truncate_diff(
                local_diff, max_per_file=max_per_file, max_total=max_total
            )

    # Latency metrics tracker is optional.
    _metrics_tracker = None
    try:
        _metrics_tracker = getattr(services.get("health_tracker"), "metrics", None)
    except Exception:
        pass

    try:
        # Embed query for vector search — required for PostgreSQL/CloudSQL backends
        # LanceDB handles string queries natively, but PostgreSQL needs a real vector
        query_vector = body.query  # default: pass raw text (works for LanceDB)
        embedding_service = services.get("embedding_service")
        capabilities = services.get("capabilities")
        if capabilities and getattr(capabilities, "uses_server_side_embedding", False):
            # AlloyDB: pass raw text, DB generates embedding via SQL function
            query_vector = body.query
        elif embedding_service:
            # Local embedding: generate vector from query text
            query_vector = await embedding_service.embed_async(body.query)

        ctx = (
            _metrics_tracker.track_latency("search")
            if _metrics_tracker
            else nullcontext()
        )
        _search_start = time.perf_counter()
        with ctx:
            results = await search_service.hybrid_search(
                query_vector=query_vector,
                query_fts=body.query,
                limit=body.limit,
                content_preference=body.content_preference,
                branch=body.branch,
            )
        query_time_ms = round((time.perf_counter() - _search_start) * 1000, 1)

        # Build set of locally-modified paths for annotation (WS3)
        local_modified_paths: set[str] = set()
        if local_diff and local_diff.modified_files:
            local_modified_paths = {f.path for f in local_diff.modified_files}

        formatted = []
        for r in results:
            data = getattr(r, "data", {}) or {}
            file_path: str = data.get("file_path", "unknown")
            entry = {
                "file_path": file_path,
                "content": data.get("content", "")[:500],
                "chunk_type": data.get("chunk_type", "code"),
                "content_type": data.get("content_type", "CODE"),
                "score": getattr(r, "score", getattr(r, "relevance_score", 0.0)),
            }
            # Annotate with local diff overlay
            if local_modified_paths:
                entry["local_modified"] = file_path in local_modified_paths

            formatted.append(entry)

        response: dict = {
            "query": body.query,
            "results": formatted,
            "total": len(formatted),
            "count": len(formatted),  # kept for backward compatibility
            "query_time_ms": query_time_ms,
        }

        # Include local changes summary for AI context (WS3 AC-3.3)
        if local_diff and local_diff.modified_files:
            # Prefer branch from local_diff; fall back to the top-level request
            # branch so that callers who set only body.branch still see it echoed.
            effective_branch = local_diff.branch or body.branch
            response["local_changes_summary"] = {
                "branch": effective_branch,
                "modified_file_count": len(local_diff.modified_files),
                "modified_files": [f.path for f in local_diff.modified_files],
                "truncated": local_diff.truncated,
                "omitted_count": local_diff.omitted_count,
            }

        return response

    except Exception:
        logger.exception("Search failed")
        return {"error": "Search failed", "code": "SEARCH_ERROR"}
