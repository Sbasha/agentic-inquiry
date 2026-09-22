"""
TEST_01: Core Functionality — full protocol.

Validates: server health, session management, indexing, search quality,
memory persistence, and tool availability.
"""
import time
from pathlib import Path
from typing import Any, Dict

from .base import (
    CODEBASE_PATH,
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

TEST_ID = "01"
SLUG = "core"


async def run(
    services: dict,
    test_id: str,
    slug: str,
    run_id: str,
    output_dir: Path,
) -> Dict[str, Any]:
    from agentic_inquiry.mcp.tools.session import get_session
    from agentic_inquiry.mcp.tools.search import search_knowledge
    from agentic_inquiry.mcp.tools.memory import save_memory, recall_memories
    from agentic_inquiry.mcp.tools.info import get_server_info, get_project_info
    from agentic_inquiry.mcp.tools.context import build_context

    results: Dict[str, Any] = {}
    issues: list = []
    journal: list = []  # Running adoption observations
    t_start = time.time()

    # ── T1: Server Health ───────────────────────────────────────
    log(test_id, "T1: Server health check")
    try:
        r, t = await call_tool(get_server_info, services=services)
        health_ok = "error" not in r and t < 2.0
        check(results, issues, "T1_server_health", health_ok, {
            "response_time_s": round(t, 2),
            "has_projects": bool(r.get("projects")),
        }, fail_msg=f"Server health: {r.get('error', 'slow response')}")
        if health_ok:
            note_adoption(journal, f"Server responds in {t:.1f}s — fast enough for interactive use", "positive")
        else:
            note_adoption(journal, f"Server slow ({t:.1f}s) or unhealthy — agent would retry or skip", "negative")
    except Exception as e:
        check(results, issues, "T1_server_health", False, severity="CRITICAL", fail_msg=str(e))
        note_adoption(journal, f"Server unreachable: {e} — agent cannot use this tool at all", "blocker")
        return summarize(test_id, slug, results, issues, time.time() - t_start, adoption_journal=journal)

    # ── T2: Session Management ──────────────────────────────────
    log(test_id, "T2: Session management")
    try:
        session_id, project_id = await create_test_session(
            services, test_id, slug, run_id,
            description="Core functionality smoke test",
        )
        check(results, issues, "T2_1_create_session", True, {"session_id": session_id})

        # T2.2: Retrieve session
        r, t = await call_tool(get_session, services=services, session_id=session_id)
        retrieved_ok = r.get("session_id") == session_id
        check(results, issues, "T2_2_retrieve_session", retrieved_ok, {
            "matches": retrieved_ok,
            "elapsed_s": round(t, 2),
        })
        note_adoption(journal, "Session created and retrievable — state management works", "positive")
    except Exception as e:
        check(results, issues, "T2_1_create_session", False, severity="CRITICAL", fail_msg=str(e))
        note_adoption(journal, f"Cannot create sessions: {e}", "blocker")
        return summarize(test_id, slug, results, issues, time.time() - t_start, adoption_journal=journal)

    # ── T3: Basic Indexing ──────────────────────────────────────
    log(test_id, "T3: Indexing")
    idx = await index_and_wait(
        services, session_id, project_id, test_id,
        source=TOOLS_PATH,
        max_wait=300,
        poll_interval=5,
    )
    check(
        results, issues, "T3_1_indexing",
        idx.get("completed", False),
        detail=idx,
        fail_msg=idx.get("error", "Indexing failed"),
    )

    # T3.2: Verify indexed content — use search as the ground truth
    # (get_project_info counts may be 0 with shared server due to project scoping)
    r, t = await call_tool(
        search_knowledge, services=services, session_id=session_id,
        query="function", limit=1,
    )
    has_content = len(r.get("results", [])) > 0
    check(results, issues, "T3_2_verify_content", has_content, {
        "search_returns_results": has_content,
        "elapsed_s": round(t, 2),
    })

    # ── T4: Basic Search ────────────────────────────────────────
    log(test_id, "T4: Search")
    r, t = await call_tool(
        search_knowledge,
        services=services,
        session_id=session_id,
        query="session management create",
        limit=5,
    )
    result_count = len(r.get("results", []))
    check(results, issues, "T4_1_search", result_count > 0, {
        "result_count": result_count,
        "elapsed_s": round(t, 2),
    })
    if result_count > 0:
        note_adoption(journal, f"Search returned {result_count} results in {t:.1f}s for 'session management' — grep would need exact string match", "positive")
    else:
        note_adoption(journal, "Search returned 0 results — agent would fall back to grep", "negative")

    # T4.2: Result quality — top result should have a file path
    top = r.get("results", [None])[0] if result_count > 0 else None
    has_path = bool(top and (top.get("file_path") or top.get("metadata", {}).get("file_path")))
    check(results, issues, "T4_2_result_quality", has_path, {
        "top_has_path": has_path,
        "top_score": top.get("score") if top else None,
    })
    if has_path and top:
        note_adoption(journal, f"Top result has file path and score={top.get('score', '?')} — actionable for code navigation", "positive")
    if t > 5.0:
        note_adoption(journal, f"search took {t:.1f}s — for simple keyword lookups, grep is faster and has zero setup cost", "neutral")
    elif t > 2.0:
        note_adoption(journal, f"search took {t:.1f}s — acceptable for semantic queries but grep returns exact matches instantly", "neutral")

    # ── T5: Basic Memory ────────────────────────────────────────
    log(test_id, "T5: Memory")
    r, t = await call_tool(
        save_memory,
        services=services,
        session_id=session_id,
        summary="Entry point is main.py:main()",
        content="The main entry point for the CLI is in main.py",
    )
    check(results, issues, "T5_1_store_memory", bool(r.get("memory_id")), {
        "memory_id": r.get("memory_id"),
    })

    r, t = await call_tool(
        recall_memories,
        services=services,
        session_id=session_id,
        query="entry point main",
        limit=3,
    )
    memories = r.get("memories", [])
    check(results, issues, "T5_2_retrieve_memory", len(memories) > 0, {
        "count": len(memories),
        "elapsed_s": round(t, 2),
    })
    if len(memories) > 0:
        note_adoption(journal, "Memory round-trips work — agent can accumulate knowledge across queries", "positive")
    else:
        note_adoption(journal, "Memory recall returned nothing — agent loses context between queries", "negative")

    # ── T6: Tool Availability ───────────────────────────────────
    log(test_id, "T6: Tool availability (via build_context)")
    try:
        r, t = await call_tool(
            build_context,
            services=services,
            session_id=session_id,
            query="project overview",
            max_tokens=500,
        )
        # build_context returning without error means the tool pipeline works
        has_content = bool(r.get("context") or r.get("sections"))
        check(results, issues, "T6_tool_availability", True, {
            "build_context_works": True,
            "has_content": has_content,
            "elapsed_s": round(t, 2),
        })
    except Exception as e:
        check(results, issues, "T6_tool_availability", False, fail_msg=str(e))

    # Honest overall assessment
    total_elapsed = time.time() - t_start
    note_adoption(journal,
        f"full core test took {total_elapsed:.0f}s including indexing — an agent doing a quick lookup would be faster with grep than waiting for index to build",
        "neutral")

    summary = summarize(test_id, slug, results, issues, time.time() - t_start, project_id, adoption_journal=journal)
    write_results(output_dir, summary)
    log(test_id, f"Done: {summary['pass_rate']} in {summary['elapsed']}s")
    return summary
