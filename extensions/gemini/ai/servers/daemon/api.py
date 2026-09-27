"""ai Daemon API - aiohttp route handlers.

All endpoints follow the pattern:
- Accept JSON POST body
- Return JSON response
- Respect timing budgets
- Graceful degradation on errors
"""

import asyncio
import logging
import time

from aiohttp import web

logger = logging.getLogger("ai.daemon.api")


def create_app(daemon) -> web.Application:
    """Create the aiohttp application with all routes."""
    app = web.Application()
    app["daemon"] = daemon

    app.router.add_get("/health", health_handler)
    app.router.add_post("/context/assemble", context_assemble_handler)
    app.router.add_post("/memory/store", memory_store_handler)
    app.router.add_post("/memory/recall", memory_recall_handler)
    app.router.add_post("/turn/increment", turn_increment_handler)
    app.router.add_post("/cache/prefetch", cache_prefetch_handler)
    app.router.add_post("/cache/invalidate", cache_invalidate_handler)
    app.router.add_post("/hooks/post_read", hooks_post_read_handler)
    app.router.add_post("/hooks/post_write", hooks_post_write_handler)
    app.router.add_post("/hooks/post_bash", hooks_post_bash_handler)
    app.router.add_post("/hooks/post_task_update", hooks_post_task_update_handler)
    app.router.add_post("/hooks/pre_compact", hooks_pre_compact_handler)
    app.router.add_post("/hooks/stop", hooks_stop_handler)
    app.router.add_post("/shutdown", shutdown_handler)

    return app


async def health_handler(request: web.Request) -> web.Response:
    """Health check: daemon status, uptime, project count."""
    daemon = request.app["daemon"]
    orch = daemon.get_orchestrator()
    return web.json_response(
        {
            "status": "ok",
            "workspace": daemon.workspace,
            "project_id": daemon.project_id,
            "uptime": daemon.uptime_seconds,
            "initialized": orch.initialized,
            "turn_count": orch.turn_count,
        }
    )


async def context_assemble_handler(request: web.Request) -> web.Response:
    """Signal analysis + context assembly for UserPromptSubmit."""
    start = time.monotonic()
    try:
        data = await request.json()
        prompt = data.get("prompt", "")
        session_id = data.get("session_id", "")

        orch = request.app["daemon"].get_orchestrator()
        if not orch.initialized:
            await orch.initialize()

        result = await orch.assemble_context(
            prompt=prompt,
            session_id=session_id,
        )

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.debug("Context assembly: %.1fms", elapsed_ms)

        return web.json_response(
            {
                "context": result.get("context", ""),
                "tier": result.get("tier", "NONE"),
                "score": result.get("score", 0),
                "elapsed_ms": round(elapsed_ms, 1),
            }
        )
    except Exception:
        logger.exception("Context assembly failed")
        return web.json_response(
            {"context": "", "tier": "NONE", "score": 0, "error": "assembly_failed"},
            status=200,  # Always 200 for hooks - graceful degradation
        )


async def memory_store_handler(request: web.Request) -> web.Response:
    """Store a memory."""
    try:
        data = await request.json()
        orch = request.app["daemon"].get_orchestrator()
        if not orch.initialized:
            await orch.initialize()

        result = await orch.store_memory(
            content=data.get("content", ""),
            category=data.get("category", "observation"),
            importance=data.get("importance", 0.7),
            metadata=data.get("metadata"),
            file_paths=data.get("file_paths"),
            entity_names=data.get("entity_names"),
        )

        return web.json_response({"stored": True, "id": result})
    except Exception:
        logger.exception("Memory store failed")
        return web.json_response({"stored": False, "error": "store_failed"})


async def memory_recall_handler(request: web.Request) -> web.Response:
    """Query memories with project isolation."""
    try:
        data = await request.json()
        orch = request.app["daemon"].get_orchestrator()
        if not orch.initialized:
            await orch.initialize()

        memories = await orch.recall_memories(
            query=data.get("query", ""),
            limit=data.get("limit", 5),
            include_global=data.get("include_global", False),
        )

        return web.json_response({"memories": memories})
    except Exception:
        logger.exception("Memory recall failed")
        return web.json_response({"memories": [], "error": "recall_failed"})


async def turn_increment_handler(request: web.Request) -> web.Response:
    """Increment turn counter, trigger checkpoints."""
    try:
        data = await request.json()
        orch = request.app["daemon"].get_orchestrator()

        turn = orch.increment_turn()
        checkpoint_due = orch.is_checkpoint_due()

        return web.json_response(
            {
                "turn": turn,
                "checkpoint_due": checkpoint_due,
            }
        )
    except Exception:
        return web.json_response({"turn": 0, "checkpoint_due": False})


async def cache_prefetch_handler(request: web.Request) -> web.Response:
    """Queue predicted queries for pre-assembly."""
    try:
        data = await request.json()
        orch = request.app["daemon"].get_orchestrator()
        if not orch.initialized:
            await orch.initialize()

        queries = data.get("queries", [])
        session_id = data.get("session_id", "")

        # Fire-and-forget: queue for background worker
        asyncio.create_task(orch.prefetch(queries, session_id))

        return web.json_response({"queued": len(queries)})
    except Exception:
        return web.json_response({"queued": 0})


async def cache_invalidate_handler(request: web.Request) -> web.Response:
    """Invalidate caches on file changes."""
    try:
        data = await request.json()
        orch = request.app["daemon"].get_orchestrator()

        file_paths = data.get("file_paths", [])
        orch.invalidate_cache(file_paths)

        return web.json_response({"invalidated": True})
    except Exception:
        return web.json_response({"invalidated": False})


async def hooks_post_read_handler(request: web.Request) -> web.Response:
    """Classify file importance after Read."""
    try:
        data = await request.json()
        orch = request.app["daemon"].get_orchestrator()

        file_path = data.get("file_path", "")
        suggestion = orch.classify_file_importance(file_path)

        return web.json_response({"suggestion": suggestion})
    except Exception:
        return web.json_response({"suggestion": None})


async def hooks_post_write_handler(request: web.Request) -> web.Response:
    """Store change event after Write/Edit."""
    try:
        data = await request.json()
        orch = request.app["daemon"].get_orchestrator()
        if not orch.initialized:
            await orch.initialize()

        file_path = data.get("file_path", "")
        change_type = data.get("change_type", "edit")

        # Fire-and-forget store
        asyncio.create_task(orch.record_file_change(file_path, change_type))

        return web.json_response({"recorded": True})
    except Exception:
        return web.json_response({"recorded": False})


async def hooks_post_bash_handler(request: web.Request) -> web.Response:
    """Classify command, extract results after Bash."""
    try:
        data = await request.json()
        orch = request.app["daemon"].get_orchestrator()

        command = data.get("command", "")
        exit_code = data.get("exit_code", 0)
        output = data.get("output", "")

        result = orch.classify_bash_command(command, exit_code, output)

        return web.json_response(result)
    except Exception:
        return web.json_response({"category": "unknown"})


async def hooks_post_task_update_handler(request: web.Request) -> web.Response:
    """Status transition prompts after TaskUpdate."""
    try:
        data = await request.json()
        orch = request.app["daemon"].get_orchestrator()

        task_id = data.get("task_id", "")
        status = data.get("status", "")
        subject = data.get("subject", "")

        prompt = orch.get_task_transition_prompt(task_id, status, subject)

        return web.json_response({"prompt": prompt})
    except Exception:
        return web.json_response({"prompt": None})


async def hooks_pre_compact_handler(request: web.Request) -> web.Response:
    """Snapshot working memory before compaction (HARD GATE)."""
    try:
        data = await request.json()
        orch = request.app["daemon"].get_orchestrator()
        if not orch.initialized:
            await orch.initialize()

        snapshot = await orch.pre_compact_snapshot(
            session_id=data.get("session_id", ""),
        )

        return web.json_response(
            {
                "snapshot_stored": snapshot.get("stored", False),
                "prompt": snapshot.get("prompt", ""),
            }
        )
    except Exception:
        logger.exception("Pre-compact snapshot failed")
        return web.json_response(
            {
                "snapshot_stored": False,
                "prompt": "[ai] WARNING: Pre-compact snapshot failed. REQUIRED: Manually store key decisions and discoveries NOW before context compresses.",
            }
        )


async def hooks_stop_handler(request: web.Request) -> web.Response:
    """Session summary generation (HARD GATE)."""
    try:
        data = await request.json()
        orch = request.app["daemon"].get_orchestrator()
        if not orch.initialized:
            await orch.initialize()

        summary = await orch.session_stop(
            session_id=data.get("session_id", ""),
        )

        return web.json_response(
            {
                "summary_stored": summary.get("stored", False),
                "prompt": summary.get("prompt", ""),
            }
        )
    except Exception:
        logger.exception("Stop handler failed")
        return web.json_response(
            {
                "summary_stored": False,
                "prompt": "[ai] WARNING: Session summary failed. REQUIRED: Store any decisions, patterns, or gotchas before session ends.",
            }
        )


async def shutdown_handler(request: web.Request) -> web.Response:
    """Graceful shutdown."""
    daemon = request.app["daemon"]
    logger.info("Shutdown requested via API")

    # Schedule shutdown after response
    asyncio.get_event_loop().call_later(0.5, daemon._shutdown_event.set)

    return web.json_response({"shutting_down": True})
