"""
Generic smoke test — 5 checks per test with adoption journal.

Used as fallback for tests that don't have a full protocol module yet.
Covers: session, indexing, search, memory_save, memory_recall.
"""
import time
from pathlib import Path
from typing import Any, Dict

from .base import (
    TOOLS_PATH,
    call_tool,
    check,
    create_test_session,
    index_and_wait,
    log,
    note_adoption,
    summarize,
    write_results,
)


async def run(
    services: dict,
    test_id: str,
    slug: str,
    run_id: str,
    output_dir: Path,
) -> Dict[str, Any]:
    """Run a generic smoke test with shared services."""
    from agentic_inquiry.mcp.tools.search import search_knowledge
    from agentic_inquiry.mcp.tools.memory import save_memory, recall_memories

    results: Dict[str, Any] = {}
    issues: list = []
    journal: list = []
    t_start = time.time()

    # 1. Session
    try:
        session_id, project_id = await create_test_session(
            services, test_id, slug, run_id,
        )
        check(results, issues, "session", True, {"session_id": session_id})
        note_adoption(journal, "session created successfully — basic state management works", "positive")
        log(test_id, f"Session: {session_id}")
    except Exception as e:
        check(results, issues, "session", False, severity="CRITICAL", fail_msg=str(e))
        note_adoption(journal, f"cannot create session: {e} — tool is unusable", "blocker")
        return summarize(test_id, slug, results, issues, time.time() - t_start, adoption_journal=journal)

    # 2. Index (small subset for speed)
    idx = await index_and_wait(
        services, session_id, project_id, test_id,
        source=TOOLS_PATH,
        max_wait=120,
        poll_interval=5,
    )
    idx_ok = idx.get("completed", False)
    check(
        results, issues, "indexing",
        idx_ok,
        detail=idx,
        fail_msg=idx.get("error", "Indexing failed"),
    )
    if idx_ok:
        elapsed = idx.get("elapsed_s", 0)
        note_adoption(journal,
            f"indexed MCP tools directory in {elapsed:.0f}s — pre-built knowledge base ready",
            "positive")
    else:
        note_adoption(journal, "indexing failed — agent cannot build knowledge base", "blocker")

    # 3. Search
    r, t = await call_tool(
        search_knowledge,
        services=services,
        session_id=session_id,
        query="session management create",
        limit=5,
    )
    count = len(r.get("results", []))
    check(results, issues, "search", count > 0, {"result_count": count, "elapsed_s": round(t, 2)})
    if count > 0:
        note_adoption(journal,
            f"semantic search returned {count} results in {t:.1f}s for '{slug}' workflow — finds conceptual matches grep would miss",
            "positive")
    else:
        note_adoption(journal,
            "search returned 0 results — agent would fall back to grep",
            "negative")
    log(test_id, f"Search: {count} results")

    # 4. Memory save
    r, t = await call_tool(
        save_memory,
        services=services,
        session_id=session_id,
        summary=f"Test memory for {slug}",
        content=f"Test memory entry for {slug} UAT run {run_id}",
    )
    mem_ok = bool(r.get("memory_id"))
    check(results, issues, "memory_save", mem_ok)

    # 5. Memory recall
    r, t = await call_tool(
        recall_memories,
        services=services,
        session_id=session_id,
        query=f"Test memory {slug}",
        limit=3,
    )
    recall_ok = bool(r.get("memories"))
    check(results, issues, "memory_recall", recall_ok)
    if mem_ok and recall_ok:
        note_adoption(journal,
            "memory save/recall works — agent can accumulate knowledge across interactions, grep cannot",
            "positive")
    elif not mem_ok:
        note_adoption(journal, "memory save failed — agent loses knowledge between sessions", "negative")
    log(test_id, f"Memory: save={results['memory_save']['pass']}, recall={results['memory_recall']['pass']}")

    summary = summarize(test_id, slug, results, issues, time.time() - t_start, project_id, adoption_journal=journal)
    write_results(output_dir, summary)
    return summary
