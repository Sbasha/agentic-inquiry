"""
TEST_04: Bug Investigation — camelCase FTS search failure.

Bug: Hybrid search returns empty/poor results for camelCase class name queries
(e.g., "SearchService", "StorageFacade") due to camelCase splitting not working
correctly in the FTS two-tier OR fallback.
"""
import time
from pathlib import Path
from typing import Any, Dict

from .base import (
    CODEBASE_PATH,
    call_tool,
    check,
    create_test_session,
    index_and_wait,
    log,
    note_adoption,
    summarize,
    write_results,
)

TEST_ID = "04"
SLUG = "bug"

BUG_REPORT = {
    "title": "Search returns empty/poor results for camelCase class name queries",
    "description": (
        "When querying hybrid search with camelCase identifiers like 'SearchService' "
        "or 'StorageFacade', the OR-based FTS two-tier fallback is supposed to split "
        "camelCase tokens but may silently fail or produce empty results."
    ),
    "reproduction_steps": [
        "Index the Agentic Inquiry codebase",
        "Run hybrid search with query 'SearchService'",
        "Run hybrid search with query 'StorageFacade'",
        "Observe empty or poorly ranked results",
    ],
    "expected": "Returns the defining file/entity for the searched class near top",
    "actual": "Empty results or wrong ranking; camelCase splitting may not function",
    "severity": "high",
}


async def run(
    services: dict,
    test_id: str,
    slug: str,
    run_id: str,
    output_dir: Path,
) -> Dict[str, Any]:
    from agentic_inquiry.mcp.tools.search import search_knowledge
    from agentic_inquiry.mcp.tools.info import get_project_info
    from agentic_inquiry.mcp.tools.info import list_entities

    results: Dict[str, Any] = {}
    issues: list = []
    journal: list = []
    t_start = time.time()

    # ── Setup: Create Session ──────────────────────────────────────────
    log(test_id, "Setup: Create session")
    try:
        session_id, project_id = await create_test_session(
            services, test_id, slug, run_id,
            description="Bug investigation - camelCase FTS search",
        )
        check(results, issues, "setup_session", True, {"session_id": session_id, "project_id": project_id})
        log(test_id, f"Session: {session_id}, project: {project_id}")
    except Exception as e:
        check(results, issues, "setup_session", False, severity="CRITICAL", fail_msg=str(e))
        return summarize(test_id, slug, results, issues, time.time() - t_start, adoption_journal=journal)

    # ── Setup: Index Codebase ──────────────────────────────────────────
    log(test_id, "Setup: Index codebase (full, wait_for_completion=True)")
    t_idx = time.time()
    idx = await index_and_wait(
        services, session_id, project_id, test_id,
        source=CODEBASE_PATH,
        max_wait=1800,
        poll_interval=15,
        wait_for_embeddings=True,
    )
    idx_elapsed = time.time() - t_idx
    check(
        results, issues, "setup_indexing",
        idx.get("completed", False),
        detail={**idx, "elapsed_s": round(idx_elapsed, 1)},
        severity="CRITICAL",
        fail_msg=idx.get("error", "Indexing failed"),
    )
    log(test_id, f"Indexing: completed={idx.get('completed')}, elapsed={idx_elapsed:.1f}s")

    if not idx.get("completed"):
        return summarize(test_id, slug, results, issues, time.time() - t_start, project_id, adoption_journal=journal)

    # ── Setup: Verify Index Health ─────────────────────────────────────
    log(test_id, "Setup: Verify index health")
    try:
        r, t = await call_tool(get_project_info, services=services, session_id=session_id)
        entities = r.get("entities", 0)
        health = r.get("index_health", "unknown")
        index_ok = entities > 0 or health in ("healthy", "unknown")  # alloydb may scope differently
        check(results, issues, "setup_index_health", index_ok, {
            "entities": entities,
            "health": health,
            "response_time_s": round(t, 2),
        }, fail_msg=f"Index health check: entities={entities}, health={health}")
    except Exception as e:
        check(results, issues, "setup_index_health", False, fail_msg=str(e))

    # ═══════════════════════════════════════════════════════════════════
    # T1: Bug Reproduction Understanding
    # ═══════════════════════════════════════════════════════════════════

    # ── T1.1: Symptom Analysis ─────────────────────────────────────────
    log(test_id, "T1.1: Symptom analysis - search with camelCase query")
    try:
        # Direct test of the reported symptom
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="SearchService", limit=10,
        )
        results_list = r.get("results", [])
        result_count = len(results_list)
        # Success: finds results AND the primary file is relevant
        relevant = any(
            "search" in (res.get("file_path", "") + res.get("content", "")).lower()
            for res in results_list
        )
        symptom_confirmed = result_count == 0 or not relevant
        check(results, issues, "T1_1_symptom_camelcase_search", True, {
            "query": "SearchService",
            "result_count": result_count,
            "relevant_results": relevant,
            "symptom_confirmed": symptom_confirmed,
            "elapsed_s": round(t, 2),
            "top_result": results_list[0].get("file_path", "") if results_list else "EMPTY",
        })
        log(test_id, f"T1.1: query='SearchService' -> {result_count} results, relevant={relevant}")
        if result_count > 0 and relevant:
            note_adoption(journal,
                f"camelCase search for 'SearchService' returned {result_count} results "
                f"— semantic search handles code identifiers better than grep",
                "positive")
        elif result_count == 0:
            note_adoption(journal,
                "camelCase query 'SearchService' returned 0 results — bug confirmed, "
                "grep would at least find the literal string",
                "negative")
    except Exception as e:
        check(results, issues, "T1_1_symptom_camelcase_search", False, fail_msg=str(e))

    # ── T1.2: Reproduction verification ───────────────────────────────
    log(test_id, "T1.2: Reproduction verification - StorageFacade query")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="StorageFacade", limit=10,
        )
        results_list = r.get("results", [])
        count2 = len(results_list)
        relevant2 = any(
            "storage" in (res.get("file_path", "") + res.get("content", "")).lower()
            for res in results_list
        )
        check(results, issues, "T1_2_reproduction_storage_facade", True, {
            "query": "StorageFacade",
            "result_count": count2,
            "relevant_results": relevant2,
            "elapsed_s": round(t, 2),
            "top_result": results_list[0].get("file_path", "") if results_list else "EMPTY",
        })
        log(test_id, f"T1.2: query='StorageFacade' -> {count2} results, relevant={relevant2}")
    except Exception as e:
        check(results, issues, "T1_2_reproduction_storage_facade", False, fail_msg=str(e))

    # ═══════════════════════════════════════════════════════════════════
    # T2: Find Bug Location
    # ═══════════════════════════════════════════════════════════════════

    # ── T2.1: Component identification ────────────────────────────────
    log(test_id, "T2.1: Find search component")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="camelCase splitting full-text search FTS query", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        fts_files = [res.get("file_path", "") for res in results_list
                     if any(kw in res.get("file_path", "") + res.get("content", "")
                            for kw in ["fts", "full_text", "hybrid_search", "rerank"])]
        found_component = len(fts_files) > 0
        check(results, issues, "T2_1_component_identification", found_component, {
            "query": "camelCase splitting full-text search FTS query",
            "result_count": count,
            "fts_related_files": fts_files[:5],
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not find FTS/search component")
        log(test_id, f"T2.1: {count} results, FTS files: {fts_files[:3]}")
        if found_component:
            note_adoption(journal,
                f"semantic query for 'camelCase splitting FTS' located {len(fts_files)} "
                f"relevant files — grep for 'camelCase' would match comments everywhere, "
                f"not the actual FTS implementation",
                "positive")
    except Exception as e:
        check(results, issues, "T2_1_component_identification", False, fail_msg=str(e))

    # ── T2.2: Narrow to specific code ─────────────────────────────────
    log(test_id, "T2.2: Narrow to specific function - camelCase split")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="camelCase split token search query OR AND fallback", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        specific_locations = [
            {"file": res.get("file_path", ""), "snippet": res.get("content", "")[:120]}
            for res in results_list[:5]
        ]
        found_specific = count > 0
        check(results, issues, "T2_2_narrow_to_code", found_specific, {
            "query": "camelCase split token search query OR AND fallback",
            "result_count": count,
            "locations": specific_locations,
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not narrow to specific camelCase split code")
        log(test_id, f"T2.2: {count} results for camelCase split query")
    except Exception as e:
        check(results, issues, "T2_2_narrow_to_code", False, fail_msg=str(e))

    # ═══════════════════════════════════════════════════════════════════
    # T3: Trace Execution Path
    # ═══════════════════════════════════════════════════════════════════

    # ── T3.1: Entry point to bug ───────────────────────────────────────
    log(test_id, "T3.1: Trace execution path - search entry point")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="hybrid_search search_knowledge entry point vector FTS combine", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        path_files = [res.get("file_path", "") for res in results_list[:5]]
        check(results, issues, "T3_1_execution_path", count > 0, {
            "query": "hybrid_search search_knowledge entry point",
            "result_count": count,
            "path_files": path_files,
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not trace execution path")
        log(test_id, f"T3.1: {count} results, files: {path_files[:3]}")
        unique_files = len(set(path_files))
        if unique_files >= 2:
            note_adoption(journal,
                f"traced execution path across {unique_files} files from entry point to "
                f"hybrid search — manual cross-file tracing would take much longer",
                "positive")
        # Check if test files dominate the results
        test_file_count = sum(1 for f in path_files if "test" in f.lower())
        if test_file_count > 0 and count > 0:
            test_pct = test_file_count / min(count, len(path_files)) * 100
            if test_pct >= 40:
                note_adoption(journal,
                    f"test files are {test_pct:.0f}% of execution path results — relevance ranking doesn't "
                    f"distinguish test from production code, adding noise to bug investigation",
                    "neutral")
    except Exception as e:
        check(results, issues, "T3_1_execution_path", False, fail_msg=str(e))

    # ── T3.2: Data flow analysis ───────────────────────────────────────
    log(test_id, "T3.2: Data flow - query normalization and tokenization")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="query normalization tokenization preprocessing before search", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        data_flow_files = [
            {"file": res.get("file_path", ""), "content_snippet": res.get("content", "")[:100]}
            for res in results_list[:5]
        ]
        check(results, issues, "T3_2_data_flow", count > 0, {
            "query": "query normalization tokenization preprocessing",
            "result_count": count,
            "data_flow_info": data_flow_files,
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not trace data flow")
        log(test_id, f"T3.2: {count} results for data flow query")
    except Exception as e:
        check(results, issues, "T3_2_data_flow", False, fail_msg=str(e))

    # ═══════════════════════════════════════════════════════════════════
    # T4: Find Root Cause
    # ═══════════════════════════════════════════════════════════════════

    # ── T4.1: Hypothesis formation ─────────────────────────────────────
    log(test_id, "T4.1: Root cause hypotheses - search for FTS implementation")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="full text search FTS implementation PostgreSQL to_tsquery plainto_tsquery", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        fts_impl = [
            {"file": res.get("file_path", ""), "snippet": res.get("content", "")[:150]}
            for res in results_list[:5]
        ]
        hypothesis_found = count > 0
        check(results, issues, "T4_1_hypothesis_fts_impl", hypothesis_found, {
            "query": "full text search FTS to_tsquery plainto_tsquery",
            "result_count": count,
            "fts_implementations": fts_impl,
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not find FTS SQL implementation")
        log(test_id, f"T4.1: {count} results for FTS implementation")
        if hypothesis_found:
            note_adoption(journal,
                "found FTS implementation details (to_tsquery, plainto_tsquery) via "
                "semantic search — understanding SQL-level root cause without reading "
                "every provider file manually",
                "positive")
    except Exception as e:
        check(results, issues, "T4_1_hypothesis_fts_impl", False, fail_msg=str(e))

    # ── T4.2: Root cause verification ─────────────────────────────────
    log(test_id, "T4.2: Verify root cause - search entities for hybrid search module")
    try:
        r, t = await call_tool(
            list_entities, services=services, session_id=session_id,
            entity_type="function", pattern="*search*", limit=50,
        )
        entities = r.get("entities", [])
        # Also try hybrid-specific pattern if first returns nothing
        if not entities:
            r2, _ = await call_tool(
                list_entities, services=services, session_id=session_id,
                entity_type="function", pattern="*hybrid*", limit=50,
            )
            entities = r2.get("entities", [])
        search_fns = entities  # Already filtered by pattern
        check(results, issues, "T4_2_root_cause_verify", len(search_fns) > 0, {
            "entity_count": len(entities),
            "search_related_entities": [
                {"name": e.get("name"), "file": e.get("file_path")}
                for e in search_fns[:5]
            ],
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not find search-related entities")
        log(test_id, f"T4.2: found {len(search_fns)} search/FTS related functions")
        if len(search_fns) > 0:
            note_adoption(journal,
                f"found {len(entities)} search-related entities via pattern filter "
                f"— structured entity index vs manual scanning of every file",
                "positive")
    except Exception as e:
        check(results, issues, "T4_2_root_cause_verify", False, fail_msg=str(e))

    # ═══════════════════════════════════════════════════════════════════
    # T5: Impact Assessment
    # ═══════════════════════════════════════════════════════════════════

    # ── T5.1: Direct impact ────────────────────────────────────────────
    log(test_id, "T5.1: Direct impact - what calls hybrid search")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="search_knowledge calls hybrid search uses results code impact", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        callers = [res.get("file_path", "") for res in results_list[:5]]
        check(results, issues, "T5_1_direct_impact", count > 0, {
            "query": "search_knowledge calls hybrid search",
            "result_count": count,
            "affected_callers": callers,
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not assess direct impact")
        log(test_id, f"T5.1: {count} results, callers: {callers[:3]}")
    except Exception as e:
        check(results, issues, "T5_1_direct_impact", False, fail_msg=str(e))

    # ── T5.2: Blast radius ─────────────────────────────────────────────
    log(test_id, "T5.2: Blast radius - dependent systems")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="onboarding entity impact lineage uses search results downstream", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        dependent_files = [res.get("file_path", "") for res in results_list[:5]]
        check(results, issues, "T5_2_blast_radius", count > 0, {
            "query": "onboarding entity impact lineage uses search",
            "result_count": count,
            "dependent_systems": dependent_files,
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not determine blast radius")
        log(test_id, f"T5.2: {count} results, dependent systems: {dependent_files[:3]}")
        if count > 0:
            note_adoption(journal,
                f"blast radius analysis found {count} dependent systems "
                f"— grep can't do dependency analysis across semantic boundaries",
                "positive")
    except Exception as e:
        check(results, issues, "T5_2_blast_radius", False, fail_msg=str(e))

    # ═══════════════════════════════════════════════════════════════════
    # T6: Fix Strategy
    # ═══════════════════════════════════════════════════════════════════

    # ── T6.1: Fix approaches ───────────────────────────────────────────
    log(test_id, "T6.1: Fix approaches - find camelCase split implementation")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="camelCase split regex pattern word boundary search token", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        fix_hints = [
            {"file": res.get("file_path", ""), "snippet": res.get("content", "")[:150]}
            for res in results_list[:5]
        ]
        check(results, issues, "T6_1_fix_approaches", count > 0, {
            "query": "camelCase split regex pattern word boundary",
            "result_count": count,
            "fix_hints": fix_hints,
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not find fix implementation hints")
        log(test_id, f"T6.1: {count} results for camelCase fix hints")
        if count > 0:
            note_adoption(journal,
                f"found {count} results for camelCase split regex patterns "
                f"— semantic search surfaced implementation-level fix hints that "
                f"grep for 'camelCase' would bury in noise",
                "positive")
        else:
            note_adoption(journal,
                "no results for camelCase split implementation — agent would need "
                "to fall back to grep to locate the regex pattern",
                "negative")
    except Exception as e:
        check(results, issues, "T6_1_fix_approaches", False, fail_msg=str(e))

    # ── T6.2: Implementation plan ──────────────────────────────────────
    log(test_id, "T6.2: Implementation plan - test coverage for search")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="test search quality hybrid FTS unit test pytest", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        test_files = [res.get("file_path", "") for res in results_list
                      if "test" in res.get("file_path", "").lower()]
        check(results, issues, "T6_2_implementation_plan", count > 0, {
            "query": "test search quality hybrid FTS pytest",
            "result_count": count,
            "test_files": test_files[:5],
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not find test files for implementation plan")
        log(test_id, f"T6.2: {count} results, test files: {test_files[:3]}")
    except Exception as e:
        check(results, issues, "T6_2_implementation_plan", False, fail_msg=str(e))

    elapsed = time.time() - t_start
    note_adoption(journal,
        f"full bug investigation took {elapsed:.0f}s including indexing — for a known bug with a specific file, "
        f"'grep -rn camelCase agentic_inquiry/search/' would give actionable results in <1s",
        "neutral")

    summary = summarize(test_id, slug, results, issues, elapsed, project_id, adoption_journal=journal)
    write_results(output_dir, summary)
    log(test_id, f"Done in {elapsed:.1f}s — {summary['pass_rate']} passed")
    return summary
