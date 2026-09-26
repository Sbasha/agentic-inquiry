"""Context assembly endpoint - signal analysis + context gathering."""

import asyncio
import logging
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel

from agentic_inquiry.server.signals.analyzer import (
    TIER_FULL_PACKET,
    TIER_MEMORY_ONLY,
    TIER_NONE,
    TIER_RELATED_LINKS,
)

logger = logging.getLogger("ai.server.routes.context")

router = APIRouter()


class ContextAssembleRequest(BaseModel):
    prompt: str
    session_id: str = "default"
    turn: int | None = None


@router.post("/context/assemble")
async def context_assemble(request: Request, body: ContextAssembleRequest) -> dict:
    """Signal-driven context assembly."""
    start = time.monotonic()

    analyzer = request.app.state.signal_analyzer
    cache_manager = request.app.state.cache_manager
    session_state = request.app.state.session_state

    # Check cache
    cache_key = cache_manager.hash_key(body.prompt[:200], body.session_id)
    cached = cache_manager.get_context(cache_key)
    if cached is not None:
        return cached

    # Analyze signals
    signals = analyzer.analyze_signals(body.prompt)

    if signals["tier"] == TIER_NONE:
        result = {"context": "", "tier": TIER_NONE, "score": signals["score"]}
        cache_manager.put_context(cache_key, result)
        return result

    # Gather context based on tier
    context_parts = []
    services = request.app.state.services
    search_service = services.get("search_service")
    memory_system = services.get("memory_system")

    if signals["tier"] == TIER_FULL_PACKET:
        tasks = [
            _gather_memories(memory_system, body.prompt, request.app.state),
            _gather_search(search_service, body.prompt, signals),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, list):
                context_parts.extend(r)
    elif signals["tier"] == TIER_RELATED_LINKS:
        tasks = [
            _gather_memories(memory_system, body.prompt, request.app.state),
            _gather_search_links(search_service, body.prompt),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, list):
                context_parts.extend(r)
    elif signals["tier"] == TIER_MEMORY_ONLY:
        memories = await _gather_memories(memory_system, body.prompt, request.app.state)
        context_parts.extend(memories)

    # Deduplicate
    turn = body.turn or session_state.turn_count
    deduped = []
    for part in context_parts:
        content = part.get("content", "")
        if not cache_manager.is_duplicate_content(body.session_id, content, turn):
            deduped.append(part)

    # Format within token budget
    daemon_config = request.app.state.daemon_config
    token_budget = daemon_config.get("context", {}).get("token_budget", 2048)
    formatted = _format_context(deduped, signals, token_budget)

    elapsed = (time.monotonic() - start) * 1000
    logger.debug(
        "Context assembled: tier=%s score=%d parts=%d %.1fms",
        signals["tier"],
        signals["score"],
        len(deduped),
        elapsed,
    )

    result = {
        "context": formatted,
        "tier": signals["tier"],
        "score": signals["score"],
    }
    cache_manager.put_context(cache_key, result)
    return result


async def _gather_memories(memory_system, prompt: str, app_state) -> list[dict]:
    """Gather relevant memories."""
    if not memory_system:
        return []
    try:
        results = await memory_system.retrieve(
            query=prompt, limit=5, strategy="adaptive"
        )
        items = results.get("results", []) if isinstance(results, dict) else results
        output = []
        confidence_gate = app_state.daemon_config.get("context", {}).get(
            "confidence_gate", 0.7
        )
        for item in items:
            content = (
                getattr(item, "content", str(item))
                if not isinstance(item, dict)
                else item.get("content", "")
            )
            confidence = 1.0
            if hasattr(item, "memory"):
                meta = getattr(item.memory, "metadata", {}) or {}
                confidence = meta.get("confidence", 1.0)
                content = getattr(item.memory, "content", str(item))
            stale_tag = " [STALE]" if confidence < confidence_gate else ""
            output.append(
                {
                    "source": "memory",
                    "content": content,
                    "tag": f"[ai Memory{stale_tag}]",
                    "priority": 1,
                }
            )
        return output
    except Exception:
        return []


async def _gather_search(search_service, prompt: str, signals: dict) -> list[dict]:
    """Gather search results."""
    if not search_service:
        return []
    try:
        preference = "code" if signals["intent"] == "CODE" else None
        results = await search_service.hybrid_search(
            query_vector=prompt[:200],
            query_fts=prompt[:200],
            limit=5,
            content_preference=preference,
        )
        output = []
        for r in results:
            data = r.data if hasattr(r, "data") else {}
            file_path = data.get("file_path", "unknown")
            content = data.get("content", "")
            chunk_type = data.get("chunk_type", "code")
            if chunk_type == "documentation":
                tag = f"[ai Docs: {file_path}]"
                priority = 4
            else:
                line = data.get("start_line", "")
                tag = f"[ai Search: {file_path}:{line}]"
                priority = 2
            output.append(
                {
                    "source": "search",
                    "content": content[:500],
                    "tag": tag,
                    "priority": priority,
                    "file_path": file_path,
                }
            )
        return output
    except Exception:
        return []


async def _gather_search_links(search_service, prompt: str) -> list[dict]:
    """Gather search result links."""
    if not search_service:
        return []
    try:
        results = await search_service.hybrid_search(
            query_vector=prompt[:200],
            query_fts=prompt[:200],
            limit=8,
        )
        output = []
        for r in results:
            data = r.data if hasattr(r, "data") else {}
            file_path = data.get("file_path", "unknown")
            summary = data.get("content", "")[:100]
            output.append(
                {
                    "source": "link",
                    "content": f"{file_path}: {summary}",
                    "tag": "[ai Related]",
                    "priority": 3,
                }
            )
        return output
    except Exception:
        return []


def _format_context(parts: list[dict], signals: dict, token_budget: int = 2048) -> str:
    """Format context parts within token budget."""
    if not parts:
        return ""
    parts.sort(key=lambda p: p.get("priority", 5))
    char_budget = token_budget * 4
    lines = []
    used = 0
    for part in parts:
        tag = part.get("tag", "")
        content = part.get("content", "")
        line = f"{tag}\n{content}"
        if used + len(line) > char_budget:
            remaining = char_budget - used - len(tag) - 10
            if remaining > 50:
                line = f"{tag}\n{content[:remaining]}..."
            else:
                break
        lines.append(line)
        used += len(line)
    if not lines:
        return ""
    header = f"[ai Context: {signals['tier']}, score={signals['score']}]"
    return header + "\n\n" + "\n\n".join(lines)
