"""Hook endpoints - REST API for Claude Code hook scripts."""

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger("agv.server.routes.hooks")

router = APIRouter()


class PostWriteRequest(BaseModel):
    file_path: str
    change_type: str = "write"


class PostBashRequest(BaseModel):
    command: str
    exit_code: int = 0
    output: str = ""


class PostTaskUpdateRequest(BaseModel):
    task_id: str
    status: str
    subject: str = ""


class PostReadRequest(BaseModel):
    file_path: str


class PreCompactRequest(BaseModel):
    session_id: str = "default"


class StopRequest(BaseModel):
    session_id: str = "default"


class CachePrefetchRequest(BaseModel):
    queries: list[str] = []
    session_id: str = "default"


class CacheInvalidateRequest(BaseModel):
    file_paths: list[str]


@router.post("/hooks/post_write")
async def hooks_post_write(request: Request, body: PostWriteRequest) -> dict:
    """Handle post-write hook - record file change."""
    session_state = request.app.state.session_state
    cache_manager = request.app.state.cache_manager
    analyzer = request.app.state.signal_analyzer

    session_state.record_file_change(body.file_path, body.change_type)
    cache_manager.invalidate([body.file_path])

    importance = analyzer.classify_file_importance(body.file_path)
    prompt = None
    if importance == "config":
        prompt = (
            "[agv Memory] Configuration file modified. "
            "If this changes behavior, store why via /agv:memory save."
        )
    elif importance == "entry_point":
        prompt = (
            "[agv Memory] Entry point modified. "
            "Store the architectural reason for this change."
        )

    return {"recorded": True, "importance": importance, "prompt": prompt}


@router.post("/hooks/post_bash")
async def hooks_post_bash(request: Request, body: PostBashRequest) -> dict:
    """Handle post-bash hook - classify command."""
    analyzer = request.app.state.signal_analyzer
    return analyzer.classify_bash_command(body.command, body.exit_code, body.output)


@router.post("/hooks/post_task_update")
async def hooks_post_task_update(request: Request, body: PostTaskUpdateRequest) -> dict:
    """Handle post-task-update hook - generate transition prompt."""
    analyzer = request.app.state.signal_analyzer
    prompt = analyzer.get_task_transition_prompt(body.task_id, body.status, body.subject)
    return {"prompt": prompt}


@router.post("/hooks/post_read")
async def hooks_post_read(request: Request, body: PostReadRequest) -> dict:
    """Handle post-read hook - classify file importance."""
    analyzer = request.app.state.signal_analyzer
    importance = analyzer.classify_file_importance(body.file_path)
    return {"importance": importance}


@router.post("/hooks/pre_compact")
async def hooks_pre_compact(request: Request, body: PreCompactRequest) -> dict:
    """Handle pre-compact hook - snapshot working memory."""
    session_state = request.app.state.session_state
    changes = session_state.pending_changes

    prompt_parts = []
    if changes:
        files = list({c["file_path"] for c in changes})
        prompt_parts.append(f"[agv] Auto-saved {len(files)} file changes.")
        session_state.clear_changes()

    prompt = (
        "[agv Pre-Compact] Context is about to compress. "
        "REQUIRED: Store any decisions, discoveries, or reusable patterns "
        "from this work NOW via /agv:memory save. "
        "Run TaskList to check completed and in-progress tasks. "
        "For each, evaluate: did it produce a decision, gotcha, or pattern?\n"
    )

    if prompt_parts:
        prompt = "\n".join(prompt_parts) + "\n\n" + prompt

    return {"stored": bool(changes), "prompt": prompt}


@router.post("/hooks/stop")
async def hooks_stop(request: Request, body: StopRequest) -> dict:
    """Handle stop hook - generate reflection prompt."""
    session_state = request.app.state.session_state
    changes = session_state.pending_changes

    if changes:
        session_state.clear_changes()

    prompt = (
        "[agv Stop] Session ending. "
        "REQUIRED: Review your work this session. Run TaskList to see completed tasks. "
        "For EACH completed task, store via /agv:memory save:\n"
        "- Decisions made (with rationale and alternatives considered)\n"
        "- Gotchas discovered (things that weren't obvious)\n"
        "- Patterns learned (reusable approaches)\n"
        "- Architecture insights (how components connect)\n\n"
        "If nothing was learned, explicitly state why. "
        "Do NOT end session without storing learnings."
    )

    return {"stored": bool(changes), "prompt": prompt}


@router.post("/cache/prefetch")
async def cache_prefetch(request: Request, body: CachePrefetchRequest) -> dict:
    """Prefetch and warm cache for predicted follow-up queries."""
    cache_manager = request.app.state.cache_manager
    services = request.app.state.services
    search_service = services.get("search_service")

    prefetched = 0
    for query in body.queries[:3]:
        cache_key = cache_manager.hash_key(query, body.session_id)
        if cache_manager.get_context(cache_key) is not None:
            continue
        if search_service:
            try:
                results = await search_service.hybrid_search(
                    query_fts=query, limit=5,
                )
                cache_manager.put_context(cache_key, {"results": len(results)})
                prefetched += 1
            except Exception:
                logger.debug("Prefetch failed for query: %s", query)
    return {"prefetched": prefetched}


@router.post("/cache/invalidate")
async def cache_invalidate(request: Request, body: CacheInvalidateRequest) -> dict:
    """Invalidate caches for changed files."""
    count = request.app.state.cache_manager.invalidate(body.file_paths)
    return {"invalidated": count}
