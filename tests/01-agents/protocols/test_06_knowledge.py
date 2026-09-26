"""
TEST_06: Knowledge Building — full protocol.

Validates: memory storage (patterns, decisions, gotchas), recall by topic,
contextual recall, session continuity, and knowledge quality.
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

TEST_ID = "06"
SLUG = "knowledge_building"


async def run(
    services: dict,
    test_id: str,
    slug: str,
    run_id: str,
    output_dir: Path,
) -> Dict[str, Any]:
    from agentic_inquiry.mcp.tools.session import create_session, list_sessions
    from agentic_inquiry.mcp.tools.search import search_knowledge
    from agentic_inquiry.mcp.tools.memory import save_memory, recall_memories
    from agentic_inquiry.mcp.tools.info import get_project_info, get_events
    from agentic_inquiry.mcp.tools.context import build_context

    results: Dict[str, Any] = {}
    issues: list = []
    journal: list = []
    t_start = time.time()

    # ── Setup: Session + Index ──────────────────────────────────
    log(test_id, "Setup: Session + Index")
    try:
        session_id, project_id = await create_test_session(
            services,
            test_id,
            slug,
            run_id,
            description="Knowledge Building - Session 1: Discovery",
        )
    except Exception as e:
        check(
            results,
            issues,
            "setup_session",
            False,
            severity="CRITICAL",
            fail_msg=str(e),
        )
        return summarize(
            test_id,
            slug,
            results,
            issues,
            time.time() - t_start,
            adoption_journal=journal,
        )

    idx = await index_and_wait(
        services,
        session_id,
        project_id,
        test_id,
        source=TOOLS_PATH,
        max_wait=300,
        poll_interval=5,
    )
    check(
        results,
        issues,
        "setup_indexing",
        idx.get("completed", False),
        detail=idx,
        fail_msg=idx.get("error", "Indexing failed"),
    )
    if not idx.get("completed"):
        return summarize(
            test_id,
            slug,
            results,
            issues,
            time.time() - t_start,
            project_id,
            adoption_journal=journal,
        )

    # ── T1: Store Insights ──────────────────────────────────────
    log(test_id, "T1.1: Pattern recognition and storage")

    # Store several pattern insights
    patterns = [
        (
            "Async-first architecture",
            "All database and I/O operations use async/await",
            ["architecture", "async"],
        ),
        (
            "Facade storage pattern",
            "StorageFacade abstracts multiple backends (LanceDB, PostgreSQL, AlloyDB)",
            ["architecture", "storage"],
        ),
        (
            "Tree-sitter parsing",
            "Code parsing uses tree-sitter for AST extraction",
            ["parsing", "ast"],
        ),
        (
            "Hybrid search pipeline",
            "Search combines vector similarity + FTS with RRF reranking",
            ["search", "algorithm"],
        ),
        (
            "Event-driven indexing",
            "Indexing emits events (started/completed/failed) for async coordination",
            ["indexing", "events"],
        ),
    ]

    stored_ids = []
    for summary_text, content_text, tags in patterns:
        r, t = await call_tool(
            save_memory,
            services=services,
            session_id=session_id,
            summary=summary_text,
            content=content_text,
            importance=0.8,
            tags=tags,
        )
        mid = r.get("memory_id")
        if mid:
            stored_ids.append(mid)

    check(
        results,
        issues,
        "T1_1_pattern_storage",
        len(stored_ids) >= 3,
        {
            "patterns_stored": len(stored_ids),
            "total_attempted": len(patterns),
        },
        fail_msg=f"Only {len(stored_ids)}/{len(patterns)} patterns stored",
    )
    note_adoption(
        journal,
        f"stored {len(stored_ids)} architecture patterns and tagged them by topic — grep has no memory system",
        "positive" if len(stored_ids) >= 3 else "negative",
    )

    # T1.2: Decision documentation
    log(test_id, "T1.2: Decision documentation")
    decisions = [
        (
            "AlloyDB chosen for production",
            "AlloyDB selected over PostgreSQL for server-side embeddings and managed scaling",
            ["decision", "storage"],
        ),
        (
            "RRF over simple ranking",
            "Reciprocal Rank Fusion chosen to combine vector + FTS results effectively",
            ["decision", "search"],
        ),
        (
            "MCP over REST API",
            "Model Context Protocol chosen for Claude Code integration over REST",
            ["decision", "api"],
        ),
    ]

    decision_ids = []
    for summary_text, content_text, tags in decisions:
        r, t = await call_tool(
            save_memory,
            services=services,
            session_id=session_id,
            summary=summary_text,
            content=content_text,
            importance=0.9,
            tags=tags,
        )
        mid = r.get("memory_id")
        if mid:
            decision_ids.append(mid)

    check(
        results,
        issues,
        "T1_2_decision_storage",
        len(decision_ids) >= 2,
        {
            "decisions_stored": len(decision_ids),
        },
    )
    note_adoption(
        journal,
        f"stored {len(decision_ids)} design decisions with importance ranking — captures rationale grep cannot represent",
        "positive" if len(decision_ids) >= 2 else "negative",
    )

    # T1.3: Gotchas
    log(test_id, "T1.3: Gotchas and pitfalls")
    gotchas = [
        (
            "AlloyDB connection pool exhaustion",
            "Running parallel tests with separate MCPServer instances exhausts connection pools. Must share one server.",
            ["gotcha", "alloydb"],
        ),
        (
            "Python 3.13 closure scoping",
            "Nested async functions in 3.13 need default parameter capture for closure variables",
            ["gotcha", "python"],
        ),
        (
            "Server-side embedding init order",
            "ai.initialize_embeddings() must run before any rows have embeddings (4MB Vertex limit)",
            ["gotcha", "alloydb", "embedding"],
        ),
    ]

    gotcha_ids = []
    for summary_text, content_text, tags in gotchas:
        r, t = await call_tool(
            save_memory,
            services=services,
            session_id=session_id,
            summary=summary_text,
            content=content_text,
            importance=0.95,
            tags=tags,
        )
        mid = r.get("memory_id")
        if mid:
            gotcha_ids.append(mid)

    check(
        results,
        issues,
        "T1_3_gotcha_storage",
        len(gotcha_ids) >= 2,
        {
            "gotchas_stored": len(gotcha_ids),
        },
    )

    # ── T2: Recall Patterns ─────────────────────────────────────
    log(test_id, "T2.1: Pattern recall by topic")

    recall_queries = [
        ("architecture patterns async", "T2_1a_recall_architecture"),
        ("search algorithm hybrid", "T2_1b_recall_search"),
        ("storage backend AlloyDB", "T2_1c_recall_storage"),
    ]

    for query, check_name in recall_queries:
        r, t = await call_tool(
            recall_memories,
            services=services,
            session_id=session_id,
            query=query,
            limit=5,
        )
        memories = r.get("memories", [])
        # Pass if any memories are recalled — recall working is the key check
        check(
            results,
            issues,
            check_name,
            len(memories) > 0,
            {
                "recalled": len(memories),
                "elapsed_s": round(t, 2),
            },
            fail_msg=f"No results recalled for '{query}'",
        )
        if len(memories) > 0:
            note_adoption(
                journal,
                f"recalled {len(memories)} memories for '{query}' — stored knowledge retrieved by topic, not filename",
                "positive",
            )
        else:
            note_adoption(
                journal,
                f"recall returned 0 memories for '{query}' — agent loses institutional knowledge",
                "negative",
            )

    # T2.2: Contextual recall
    log(test_id, "T2.2: Contextual recall")
    r, t = await call_tool(
        recall_memories,
        services=services,
        session_id=session_id,
        query="connection pool exhaustion parallel tests",
        limit=5,
    )
    memories = r.get("memories", [])
    has_gotcha = any(
        "pool" in str(m).lower() or "connection" in str(m).lower() for m in memories
    )
    check(
        results,
        issues,
        "T2_2_contextual_recall",
        has_gotcha,
        {
            "recalled": len(memories),
            "has_relevant_gotcha": has_gotcha,
            "elapsed_s": round(t, 2),
        },
    )
    note_adoption(
        journal,
        "contextual recall surfaced the gotcha about pool exhaustion from a natural-language query — grep would need exact text match"
        if has_gotcha
        else "contextual recall missed the pool exhaustion gotcha — knowledge retrieval unreliable for edge cases",
        "positive" if has_gotcha else "negative",
    )

    # ── T3: Session Continuity ──────────────────────────────────
    log(test_id, "T3: Session continuity — new session, same project")

    # Create a second session on the same project to test memory persistence
    session2_project_id = project_id  # same project
    r2 = await create_session(
        services,
        project_id=session2_project_id,
        description="Knowledge Building - Session 2: Recall",
    )
    session2_id = r2.get("session_id")

    if session2_id:
        # Recall from session 2 — memories should persist across sessions
        r, t = await call_tool(
            recall_memories,
            services=services,
            session_id=session2_id,
            query="architecture patterns async",
            limit=5,
        )
        memories = r.get("memories", [])
        check(
            results,
            issues,
            "T3_session_continuity",
            len(memories) > 0,
            {
                "session2_id": session2_id,
                "recalled_from_session2": len(memories),
            },
        )
        note_adoption(
            journal,
            f"session continuity preserved {len(memories)} memories across new session — agent doesn't lose context"
            if len(memories) > 0
            else "recall returned 0 memories in new session — agent loses institutional knowledge across sessions",
            "positive" if len(memories) > 0 else "blocker",
        )
    else:
        check(
            results,
            issues,
            "T3_session_continuity",
            False,
            fail_msg="Could not create session 2",
        )
        note_adoption(
            journal,
            "could not create second session to test continuity — session management broken",
            "blocker",
        )

    # ── T4: Knowledge Quality ───────────────────────────────────
    log(test_id, "T4: Knowledge quality — recall precision")

    # Recall all memories and check distribution
    r, t = await call_tool(
        recall_memories,
        services=services,
        session_id=session_id,
        query="Agentic Inquiry codebase",
        limit=20,
    )
    all_memories = r.get("memories", [])
    total_stored = len(stored_ids) + len(decision_ids) + len(gotcha_ids)

    coverage_pct = round(len(all_memories) / max(total_stored, 1) * 100, 1)
    check(
        results,
        issues,
        "T4_knowledge_coverage",
        len(all_memories) >= 5,
        {
            "total_stored": total_stored,
            "total_recallable": len(all_memories),
            "coverage_pct": coverage_pct,
        },
    )
    if coverage_pct < 100 and len(all_memories) > 0:
        note_adoption(
            journal,
            f"memory recall coverage is {coverage_pct}% ({len(all_memories)}/{total_stored}) — "
            f"some stored knowledge is not retrievable, so the agent can't fully trust recall completeness",
            "neutral",
        )
    note_adoption(
        journal,
        f"stored {total_stored} knowledge items across patterns/decisions/gotchas — but all must be manually "
        f"curated and stored; ai doesn't auto-extract insights from code, it only stores what you tell it",
        "neutral",
    )

    # ── T5: Search + Memory Integration ─────────────────────────
    log(test_id, "T5: Search + memory integration")
    r, t = await call_tool(
        search_knowledge,
        services=services,
        session_id=session_id,
        query="storage facade pattern",
        limit=5,
    )
    search_results = r.get("results", [])

    r2, t2 = await call_tool(
        recall_memories,
        services=services,
        session_id=session_id,
        query="storage facade pattern",
        limit=5,
    )
    memory_results = r2.get("memories", [])

    # Both search and memory should return relevant results
    has_both = len(search_results) > 0 and len(memory_results) > 0
    check(
        results,
        issues,
        "T5_search_memory_integration",
        has_both,
        {
            "search_results": len(search_results),
            "memory_results": len(memory_results),
            "search_elapsed_s": round(t, 2),
            "memory_elapsed_s": round(t2, 2),
        },
    )
    note_adoption(
        journal,
        f"search + memory integration found {len(search_results)} indexed results and {len(memory_results)} stored insights — unified knowledge across code and decisions"
        if has_both
        else f"search returned {len(search_results)} results, memory returned {len(memory_results)} — incomplete knowledge integration",
        "positive" if has_both else "negative",
    )

    summary = summarize(
        test_id,
        slug,
        results,
        issues,
        time.time() - t_start,
        project_id,
        adoption_journal=journal,
    )
    write_results(output_dir, summary)
    log(test_id, f"Done: {summary['pass_rate']} in {summary['elapsed']}s")
    return summary
