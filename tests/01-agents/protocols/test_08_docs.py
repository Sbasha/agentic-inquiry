"""
TEST_08: Documentation Generation — Search Module (SearchService).

Validates that MCP tools can support a documentation-generation workflow:
- T1: Find all public APIs and supporting components
- T2: Understand component purpose/behavior and signatures
- T3: Map dependencies and interactions
- T4: Find and curate usage examples
- T5: Identify edge cases and limitations
- T6: Generate API reference and user guide content
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

TEST_ID = "08"
SLUG = "docs"

# Module to document
MODULE = "Search module (SearchService)"
TARGET_QUERIES = [
    "SearchService public methods",
    "search_knowledge hybrid search query",
    "search result type definition",
    "search configuration options limit",
    "search error handling validation",
]


async def run(
    services: dict,
    test_id: str,
    slug: str,
    run_id: str,
    output_dir: Path,
) -> Dict[str, Any]:
    from agentic_inquiry.mcp.tools.search import search_knowledge
    from agentic_inquiry.mcp.tools.info import get_project_info, list_entities

    results: Dict[str, Any] = {}
    issues: list = []
    journal: list = []
    t_start = time.time()

    # ── Setup: Create Session ──────────────────────────────────────────
    log(test_id, "Setup: Create session")
    try:
        session_id, project_id = await create_test_session(
            services, test_id, slug, run_id,
            description="Documentation generation - Search module",
        )
        check(results, issues, "setup_session", True, {"session_id": session_id, "project_id": project_id})
        log(test_id, f"Session: {session_id}, project: {project_id}")
    except Exception as e:
        check(results, issues, "setup_session", False, severity="CRITICAL", fail_msg=str(e))
        return summarize(test_id, slug, results, issues, time.time() - t_start, adoption_journal=journal)

    # ── Setup: Index Codebase ──────────────────────────────────────────
    log(test_id, "Setup: Index codebase (full, wait_for_completion=True, wait_timeout=1800)")
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
        stats = r.get("statistics", {})
        entities = stats.get("entities_created", r.get("entities", 0))
        chunks = stats.get("chunks_indexed", r.get("indexed_files", r.get("chunks", 0)))
        healthy = entities > 0 or chunks > 0
        check(
            results, issues, "setup_health",
            healthy,
            detail={"entities": entities, "chunks": chunks, "info": r},
            severity="HIGH",
            fail_msg=f"Index unhealthy: entities={entities}",
        )
        log(test_id, f"Index health: entities={entities}, chunks={chunks}")
    except Exception as e:
        check(results, issues, "setup_health", False, severity="HIGH", fail_msg=str(e))

    # ── T1.1: Public API Discovery ──────────────────────────────────────
    log(test_id, "T1.1: Public API discovery - SearchService classes")
    t1_queries = [
        ("SearchService public methods search", "SearchService class"),
        ("search_knowledge function definition", "search_knowledge function"),
        ("hybrid_search function definition", "hybrid_search function"),
    ]
    t1_findings = []
    t1_results_count = 0
    try:
        for query, label in t1_queries:
            r, t = await call_tool(
                search_knowledge,
                services=services,
                session_id=session_id,
                query=query,
                limit=5,
            )
            hits = r.get("results", [])
            t1_results_count += len(hits)
            t1_findings.append({"query": query, "label": label, "count": len(hits), "elapsed_s": round(t, 2)})
            log(test_id, f"  T1.1 '{label}': {len(hits)} results in {t:.2f}s")

        # Check we found something
        found_service = any(f["count"] > 0 for f in t1_findings)
        check(
            results, issues, "t1_1_api_discovery",
            found_service,
            detail={"queries": t1_findings, "total_results": t1_results_count},
            severity="HIGH",
            fail_msg="No results for public API discovery queries",
        )
        note_adoption(journal,
            f"discovered {t1_results_count} SearchService methods via semantic search — grep would need to know exact function names",
            "positive" if found_service else "negative")
    except Exception as e:
        check(results, issues, "t1_1_api_discovery", False, severity="HIGH", fail_msg=str(e))

    # ── T1.2: Supporting Components ─────────────────────────────────────
    log(test_id, "T1.2: Supporting components - types, config, exceptions")
    t1_2_findings = []
    try:
        support_queries = [
            ("SearchResult type definition", "SearchResult type"),
            ("search configuration options default limit", "SearchConfig"),
            ("search validation error exception", "Search exceptions"),
        ]
        for query, label in support_queries:
            r, t = await call_tool(
                search_knowledge,
                services=services,
                session_id=session_id,
                query=query,
                limit=5,
            )
            hits = r.get("results", [])
            t1_2_findings.append({"query": query, "label": label, "count": len(hits)})
            log(test_id, f"  T1.2 '{label}': {len(hits)} results")

        found_any = any(f["count"] > 0 for f in t1_2_findings)
        check(
            results, issues, "t1_2_supporting_components",
            found_any,
            detail={"queries": t1_2_findings},
            severity="MEDIUM",
            fail_msg="No results for supporting component queries",
        )
    except Exception as e:
        check(results, issues, "t1_2_supporting_components", False, severity="MEDIUM", fail_msg=str(e))

    # ── T2.1: Component Functionality ──────────────────────────────────
    log(test_id, "T2.1: Component functionality - understand SearchService")
    try:
        r, t = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="SearchService class purpose responsibilities hybrid vector full-text",
            limit=8,
        )
        hits = r.get("results", [])
        # Look for search service content
        relevant = [h for h in hits if "search" in (h.get("file_path", "") + h.get("content", "")).lower()]
        check(
            results, issues, "t2_1_component_functionality",
            len(relevant) > 0,
            detail={"hits": len(hits), "relevant": len(relevant), "elapsed_s": round(t, 2)},
            severity="HIGH",
            fail_msg=f"SearchService understanding query returned no relevant results (hits={len(hits)})",
        )
        note_adoption(journal,
            f"semantic query returned {len(relevant)} relevant results describing SearchService purpose — like having a knowledgeable colleague explain the code",
            "positive" if len(relevant) > 0 else "negative")
        log(test_id, f"  T2.1: {len(hits)} hits, {len(relevant)} relevant in {t:.2f}s")
    except Exception as e:
        check(results, issues, "t2_1_component_functionality", False, severity="HIGH", fail_msg=str(e))

    # ── T2.2: Parameter Analysis ────────────────────────────────────────
    log(test_id, "T2.2: Parameter analysis - search_knowledge signature")
    try:
        r, t = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="search_knowledge parameters query limit session_id content_type filter",
            limit=5,
        )
        hits = r.get("results", [])
        has_params = any(
            "limit" in h.get("content", "") or "session_id" in h.get("content", "")
            for h in hits
        )
        check(
            results, issues, "t2_2_parameter_analysis",
            len(hits) > 0,
            detail={"hits": len(hits), "has_params": has_params, "elapsed_s": round(t, 2)},
            severity="MEDIUM",
            fail_msg="Parameter analysis query returned no results",
        )
        log(test_id, f"  T2.2: {len(hits)} hits, params found={has_params}")
    except Exception as e:
        check(results, issues, "t2_2_parameter_analysis", False, severity="MEDIUM", fail_msg=str(e))

    # ── T3.1: Dependency Mapping ────────────────────────────────────────
    log(test_id, "T3.1: Dependency mapping - SearchService dependencies")
    try:
        r, t = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="SearchService imports StorageFacade EmbeddingRegistry dependencies",
            limit=6,
        )
        hits = r.get("results", [])
        check(
            results, issues, "t3_1_dependency_mapping",
            len(hits) > 0,
            detail={"hits": len(hits), "elapsed_s": round(t, 2)},
            severity="MEDIUM",
            fail_msg="Dependency mapping query returned no results",
        )
        note_adoption(journal,
            f"dependency mapping found {len(hits)} related components in {t:.2f}s — manual tracing would take minutes",
            "positive" if len(hits) >= 2 else "neutral")
        note_adoption(journal,
            f"dependency mapping found {len(hits)} components but doesn't explain HOW they connect "
            f"— agent still needs to read actual import statements and call sites in the code",
            "neutral")
        log(test_id, f"  T3.1: {len(hits)} hits in {t:.2f}s")
    except Exception as e:
        check(results, issues, "t3_1_dependency_mapping", False, severity="MEDIUM", fail_msg=str(e))

    # ── T3.2: Component Interactions ────────────────────────────────────
    log(test_id, "T3.2: Component interactions - how search pipeline works")
    try:
        r, t = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="hybrid search pipeline vector FTS reranking RRF score combination flow",
            limit=8,
        )
        hits = r.get("results", [])
        check(
            results, issues, "t3_2_component_interactions",
            len(hits) > 0,
            detail={"hits": len(hits), "elapsed_s": round(t, 2)},
            severity="MEDIUM",
            fail_msg="Component interaction query returned no results",
        )
        log(test_id, f"  T3.2: {len(hits)} hits in {t:.2f}s")
    except Exception as e:
        check(results, issues, "t3_2_component_interactions", False, severity="MEDIUM", fail_msg=str(e))

    # ── T4.1: Usage Examples ────────────────────────────────────────────
    log(test_id, "T4.1: Usage examples - where search_knowledge is called")
    try:
        r, t = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="search_knowledge usage example call await result",
            limit=8,
        )
        hits = r.get("results", [])
        # Look for test or example files
        example_hits = [h for h in hits if "test" in h.get("file_path", "").lower() or "example" in h.get("file_path", "").lower()]
        check(
            results, issues, "t4_1_usage_examples",
            len(hits) > 0,
            detail={"hits": len(hits), "example_hits": len(example_hits), "elapsed_s": round(t, 2)},
            severity="MEDIUM",
            fail_msg="Usage example query returned no results",
        )
        note_adoption(journal,
            f"found {len(example_hits)} example files showing search_knowledge usage — agent gets working examples without manual codebase traversal",
            "positive" if len(example_hits) > 0 else "neutral")
        log(test_id, f"  T4.1: {len(hits)} hits, {len(example_hits)} example files in {t:.2f}s")
    except Exception as e:
        check(results, issues, "t4_1_usage_examples", False, severity="MEDIUM", fail_msg=str(e))

    # ── T4.2: Example Curation ──────────────────────────────────────────
    log(test_id, "T4.2: Example curation - find test examples for search")
    try:
        r, t = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="test search integration hybrid search assert results query",
            limit=5,
        )
        hits = r.get("results", [])
        # Check for test files with actual search calls
        test_examples = [h for h in hits if "test" in h.get("file_path", "").lower()]
        check(
            results, issues, "t4_2_example_curation",
            len(hits) > 0,
            detail={"hits": len(hits), "test_examples": len(test_examples), "elapsed_s": round(t, 2)},
            severity="LOW",
            fail_msg="Example curation query returned no results",
        )
        log(test_id, f"  T4.2: {len(hits)} hits, {len(test_examples)} test examples")
    except Exception as e:
        check(results, issues, "t4_2_example_curation", False, severity="LOW", fail_msg=str(e))

    # ── T5.1: Edge Case Discovery ───────────────────────────────────────
    log(test_id, "T5.1: Edge case discovery - search validation and error handling")
    try:
        r, t = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="search validation input error empty query limit maximum constraint",
            limit=6,
        )
        hits = r.get("results", [])
        check(
            results, issues, "t5_1_edge_cases",
            len(hits) > 0,
            detail={"hits": len(hits), "elapsed_s": round(t, 2)},
            severity="MEDIUM",
            fail_msg="Edge case discovery query returned no results",
        )
        log(test_id, f"  T5.1: {len(hits)} hits in {t:.2f}s")
    except Exception as e:
        check(results, issues, "t5_1_edge_cases", False, severity="MEDIUM", fail_msg=str(e))

    # ── T5.2: Limitations and Constraints ──────────────────────────────
    log(test_id, "T5.2: Limitations - search thresholds and constraints")
    try:
        r, t = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="MIN_VECTOR_SCORE MIN_FTS_SCORE max_results_per_file deduplication limit constraint",
            limit=6,
        )
        hits = r.get("results", [])
        check(
            results, issues, "t5_2_limitations",
            len(hits) > 0,
            detail={"hits": len(hits), "elapsed_s": round(t, 2)},
            severity="LOW",
            fail_msg="Limitations query returned no results",
        )
        note_adoption(journal,
            f"searched for threshold constants and constraints by concept — found {len(hits)} results without knowing variable names upfront",
            "positive" if len(hits) > 0 else "negative")
        log(test_id, f"  T5.2: {len(hits)} hits in {t:.2f}s")
    except Exception as e:
        check(results, issues, "t5_2_limitations", False, severity="LOW", fail_msg=str(e))

    # ── T6.1: API Reference Generation ─────────────────────────────────
    log(test_id, "T6.1: API reference - collect full search module content")
    try:
        # Search for the main search service file
        r, t = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="SearchService class async def search hybrid_search vector_search",
            limit=10,
        )
        hits = r.get("results", [])
        search_files = list({h.get("file_path", "") for h in hits if "search" in h.get("file_path", "").lower()})
        check(
            results, issues, "t6_1_api_reference",
            len(hits) > 0,
            detail={"hits": len(hits), "search_files": search_files, "elapsed_s": round(t, 2)},
            severity="MEDIUM",
            fail_msg="API reference query returned no results",
        )
        note_adoption(journal,
            f"collected API surface across {len(search_files)} search files in one query — assembling docs from scattered files is where semantic search saves the most time",
            "positive" if len(search_files) >= 2 else "neutral")
        log(test_id, f"  T6.1: {len(hits)} hits, {len(search_files)} unique search files")
    except Exception as e:
        check(results, issues, "t6_1_api_reference", False, severity="MEDIUM", fail_msg=str(e))

    # ── T6.2: User Guide Content ────────────────────────────────────────
    log(test_id, "T6.2: User guide - quick start and setup")
    try:
        r, t = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="quick start search setup initialize SearchService create usage guide",
            limit=6,
        )
        hits = r.get("results", [])
        check(
            results, issues, "t6_2_user_guide",
            len(hits) > 0,
            detail={"hits": len(hits), "elapsed_s": round(t, 2)},
            severity="LOW",
            fail_msg="User guide query returned no results",
        )
        log(test_id, f"  T6.2: {len(hits)} hits in {t:.2f}s")
    except Exception as e:
        check(results, issues, "t6_2_user_guide", False, severity="LOW", fail_msg=str(e))

    # ── T7: Cross-Functional - List Search Entities ──────────────────
    log(test_id, "T7: List entities - verify search module entities indexed")
    try:
        r, t = await call_tool(
            list_entities,
            services=services,
            session_id=session_id,
            entity_type="class",
            limit=20,
        )
        entities = r.get("entities", [])
        search_entities = [e for e in entities if "search" in (e.get("name", "") + e.get("file_path", "")).lower()]
        check(
            results, issues, "t7_list_search_entities",
            len(entities) > 0,
            detail={"total_entities": len(entities), "search_entities": len(search_entities), "elapsed_s": round(t, 2)},
            severity="MEDIUM",
            fail_msg="list_entities returned no results",
        )
        note_adoption(journal,
            f"entity index surfaced {len(search_entities)} search-related classes from {len(entities)} total — structured inventory that grep 'class ' cannot reliably produce",
            "positive" if len(search_entities) > 0 else "neutral")
        log(test_id, f"  T7: {len(entities)} total entities, {len(search_entities)} search-related")
    except Exception as e:
        check(results, issues, "t7_list_search_entities", False, severity="MEDIUM", fail_msg=str(e))

    # ── Honest assessment: doc generation limitations ────────────────────
    note_adoption(journal,
        "semantic search finds related code snippets but cannot generate coherent documentation on its own "
        "— the agent still needs an LLM to synthesize snippets into readable docs, so ai is a research tool not a doc generator",
        "neutral")

    # ── Final Summary ────────────────────────────────────────────────────
    elapsed = time.time() - t_start
    summary = summarize(test_id, slug, results, issues, elapsed, project_id, adoption_journal=journal)
    write_results(output_dir, summary)
    log(test_id, f"Complete: {summary['pass_rate']} passed in {elapsed:.1f}s")
    return summary
