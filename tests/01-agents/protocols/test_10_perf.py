"""
TEST_10: Performance Investigation — Hybrid search query latency.

Performance Issue: Hybrid search queries take 5+ seconds for large codebases.
The search pipeline (vector + FTS + reranking) has multiple potential bottlenecks
that need to be identified and optimized.
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

TEST_ID = "10"
SLUG = "perf"

PERFORMANCE_ISSUE = {
    "title": "Hybrid search queries take 5+ seconds for large codebases",
    "description": (
        "The hybrid search pipeline combines vector similarity search with full-text "
        "search and then applies IDF-weighted reranking. Under load or with large "
        "codebases, query latency exceeds 5 seconds making real-time code intelligence unusable."
    ),
    "symptom": "Search queries take 5+ seconds",
    "current_performance": "5-10 seconds per query",
    "target_performance": "<1 second per query",
    "impact": "Makes real-time code intelligence unusable",
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
    from agentic_inquiry.mcp.tools.analysis import understand_entity
    

    results: Dict[str, Any] = {}
    issues: list = []
    journal: list = []
    t_start = time.time()

    # ── Setup: Create Session ──────────────────────────────────────────
    log(test_id, "Setup: Create session")
    try:
        session_id, project_id = await create_test_session(
            services, test_id, slug, run_id,
            description="Performance investigation - hybrid search latency",
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
    chunks_created = idx.get("chunks_created", 0)
    if idx.get("completed"):
        note_adoption(journal,
            f"{chunks_created} chunk index took {idx_elapsed:.0f}s to build — not viable for quick one-off "
            f"investigations where you already know roughly where to look",
            "neutral")

    if not idx.get("completed"):
        return summarize(test_id, slug, results, issues, time.time() - t_start, project_id, adoption_journal=journal)

    # ── Setup: Verify Index Health ─────────────────────────────────────
    log(test_id, "Setup: Verify index health")
    try:
        r, t = await call_tool(get_project_info, services=services, session_id=session_id)
        entities = r.get("entities", 0)
        health = r.get("index_health", "unknown")
        index_ok = entities > 0 or health in ("healthy", "unknown")
        check(results, issues, "setup_index_health", index_ok, {
            "entities": entities,
            "health": health,
            "response_time_s": round(t, 2),
        }, fail_msg=f"Index health check: entities={entities}, health={health}")
    except Exception as e:
        check(results, issues, "setup_index_health", False, fail_msg=str(e))

    # ═══════════════════════════════════════════════════════════════════
    # T1: Identify Bottleneck Location
    # ═══════════════════════════════════════════════════════════════════

    # ── T1.1: Find the hybrid search implementation ────────────────────
    log(test_id, "T1.1: Find hybrid search bottleneck implementation")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="hybrid search implementation vector FTS combine rerank pipeline", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        search_files = [res.get("file_path", "") for res in results_list
                        if any(kw in res.get("file_path", "") + res.get("content", "").lower()
                               for kw in ["hybrid_search", "search/", "rerank", "rrf"])]
        found_impl = len(search_files) > 0
        check(results, issues, "T1_1_bottleneck_location", found_impl, {
            "query": "hybrid search implementation vector FTS combine rerank pipeline",
            "result_count": count,
            "search_files": search_files[:5],
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not find hybrid search implementation")
        log(test_id, f"T1.1: {count} results, search files: {search_files[:3]}")
        if found_impl:
            note_adoption(journal,
                f"found {len(search_files)} bottleneck-related files via semantic search — grep for 'performance' returns too much noise",
                "positive")
        else:
            note_adoption(journal,
                "semantic search missed hybrid search implementation files — grep for 'hybrid_search' would find them instantly",
                "negative")
    except Exception as e:
        check(results, issues, "T1_1_bottleneck_location", False, fail_msg=str(e))

    # ── T1.2: Characterize bottleneck type ────────────────────────────
    log(test_id, "T1.2: Characterize bottleneck - I/O vs CPU vs DB")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="database query vector similarity search latency N+1 query async await", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        db_patterns = [
            {"file": res.get("file_path", ""), "snippet": res.get("content", "")[:120]}
            for res in results_list[:5]
        ]
        found_db = count > 0
        check(results, issues, "T1_2_bottleneck_characterization", found_db, {
            "query": "database query vector similarity search latency N+1",
            "result_count": count,
            "db_patterns": db_patterns,
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not characterize bottleneck type")
        log(test_id, f"T1.2: {count} results for DB query patterns")
        if found_db:
            note_adoption(journal,
                f"semantic search surfaced {count} DB-layer results for 'latency N+1' — cross-cutting concern grep would miss",
                "positive")
        else:
            note_adoption(journal,
                "bottleneck characterization search returned no results — agent has no leads on root cause",
                "negative")
    except Exception as e:
        check(results, issues, "T1_2_bottleneck_characterization", False, fail_msg=str(e))

    # ═══════════════════════════════════════════════════════════════════
    # T2: Understand Data Flow
    # ═══════════════════════════════════════════════════════════════════

    # ── T2.1: Data volume through search pipeline ─────────────────────
    log(test_id, "T2.1: Data volume - chunk count, embedding dimensions")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="chunk embedding dimension limit result count search candidates rerank", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        volume_info = [
            {"file": res.get("file_path", ""), "snippet": res.get("content", "")[:150]}
            for res in results_list[:5]
        ]
        found_volume = count > 0
        check(results, issues, "T2_1_data_volume", found_volume, {
            "query": "chunk embedding dimension limit result count search candidates",
            "result_count": count,
            "volume_info": volume_info,
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not find data volume information")
        log(test_id, f"T2.1: {count} results for data volume query")
    except Exception as e:
        check(results, issues, "T2_1_data_volume", False, fail_msg=str(e))

    # ── T2.2: Data structures used ────────────────────────────────────
    log(test_id, "T2.2: Data structures - lists, dicts, sets in search path")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="search result deduplication data structure aggregation merge scores", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        struct_info = [
            {"file": res.get("file_path", ""), "snippet": res.get("content", "")[:120]}
            for res in results_list[:5]
        ]
        found_structs = count > 0
        check(results, issues, "T2_2_data_structures", found_structs, {
            "query": "search result deduplication data structure aggregation",
            "result_count": count,
            "structure_info": struct_info,
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not find data structure information")
        log(test_id, f"T2.2: {count} results for data structure query")
    except Exception as e:
        check(results, issues, "T2_2_data_structures", False, fail_msg=str(e))

    # ═══════════════════════════════════════════════════════════════════
    # T3: Find Existing Optimizations
    # ═══════════════════════════════════════════════════════════════════

    # ── T3.1: Caching patterns ────────────────────────────────────────
    log(test_id, "T3.1: Find caching patterns")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="cache LRU TTL memoize cached result reuse", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        cache_patterns = [
            {"file": res.get("file_path", ""), "snippet": res.get("content", "")[:120]}
            for res in results_list[:5]
            if any(kw in res.get("content", "").lower() + res.get("file_path", "").lower()
                   for kw in ["cache", "lru", "ttl", "memoize"])
        ]
        found_cache = len(cache_patterns) > 0
        check(results, issues, "T3_1_caching_patterns", found_cache, {
            "query": "cache LRU TTL memoize cached result reuse",
            "result_count": count,
            "cache_patterns": cache_patterns[:3],
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not find caching patterns")
        log(test_id, f"T3.1: {count} results, {len(cache_patterns)} cache patterns found")
        if found_cache:
            note_adoption(journal,
                f"discovered {len(cache_patterns)} caching patterns across the codebase — structural pattern detection grep can't do",
                "positive")
        else:
            note_adoption(journal,
                "no caching patterns found — may indicate search is not surfacing implementation details",
                "neutral")
    except Exception as e:
        check(results, issues, "T3_1_caching_patterns", False, fail_msg=str(e))

    # ── T3.2: Batching patterns ───────────────────────────────────────
    log(test_id, "T3.2: Find batching patterns")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="batch size chunk bulk insert operation concurrent parallel async", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        batch_patterns = [
            {"file": res.get("file_path", ""), "snippet": res.get("content", "")[:120]}
            for res in results_list[:5]
            if any(kw in res.get("content", "").lower() + res.get("file_path", "").lower()
                   for kw in ["batch", "bulk", "concurrent", "parallel"])
        ]
        found_batch = len(batch_patterns) > 0
        check(results, issues, "T3_2_batching_patterns", found_batch, {
            "query": "batch size chunk bulk insert operation concurrent parallel",
            "result_count": count,
            "batch_patterns": batch_patterns[:3],
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not find batching patterns")
        log(test_id, f"T3.2: {count} results, {len(batch_patterns)} batch patterns found")
    except Exception as e:
        check(results, issues, "T3_2_batching_patterns", False, fail_msg=str(e))

    # ═══════════════════════════════════════════════════════════════════
    # T4: Check Configurations
    # ═══════════════════════════════════════════════════════════════════

    # ── T4.1: Performance configuration discovery ─────────────────────
    log(test_id, "T4.1: Discover performance configurations")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="pool_size max_overflow connection pool limit config performance tuning", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        config_info = [
            {"file": res.get("file_path", ""), "snippet": res.get("content", "")[:150]}
            for res in results_list[:5]
            if any(kw in res.get("content", "").lower() + res.get("file_path", "").lower()
                   for kw in ["pool_size", "limit", "timeout", "batch_size", "config"])
        ]
        found_config = count > 0
        check(results, issues, "T4_1_config_discovery", found_config, {
            "query": "pool_size max_overflow connection pool limit config performance",
            "result_count": count,
            "config_info": config_info[:3],
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not find performance configurations")
        log(test_id, f"T4.1: {count} results for performance config query")
    except Exception as e:
        check(results, issues, "T4_1_config_discovery", False, fail_msg=str(e))

    # ── T4.2: Tuning opportunities ────────────────────────────────────
    log(test_id, "T4.2: Config tuning opportunities - indexes, min_score thresholds")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="MIN_VECTOR_SCORE MIN_FTS_SCORE threshold filter pre-filter limit candidates", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        tuning_info = [
            {"file": res.get("file_path", ""), "snippet": res.get("content", "")[:150]}
            for res in results_list[:5]
        ]
        found_tuning = count > 0
        check(results, issues, "T4_2_tuning_opportunities", found_tuning, {
            "query": "MIN_VECTOR_SCORE MIN_FTS_SCORE threshold filter pre-filter",
            "result_count": count,
            "tuning_info": tuning_info[:3],
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not find tuning opportunities")
        log(test_id, f"T4.2: {count} results for tuning opportunities")
        if found_tuning:
            note_adoption(journal,
                f"tuning constants (MIN_VECTOR_SCORE, thresholds) found in {count} results — semantic search locates config knobs by purpose not name",
                "positive")
        else:
            note_adoption(journal,
                "tuning opportunity search returned nothing — grep for exact constant names would be more reliable here",
                "negative")
    except Exception as e:
        check(results, issues, "T4_2_tuning_opportunities", False, fail_msg=str(e))

    # ═══════════════════════════════════════════════════════════════════
    # T5: Identify Alternatives
    # ═══════════════════════════════════════════════════════════════════

    # ── T5.1: Alternative algorithms ─────────────────────────────────
    log(test_id, "T5.1: Alternative algorithms - RRF, BM25, approximate NN")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="RRF reciprocal rank fusion BM25 approximate nearest neighbor HNSW index", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        alt_algorithms = [
            {"file": res.get("file_path", ""), "snippet": res.get("content", "")[:150]}
            for res in results_list[:5]
            if any(kw in res.get("content", "").lower() + res.get("file_path", "").lower()
                   for kw in ["rrf", "bm25", "hnsw", "approximate", "annoy", "faiss"])
        ]
        found_alts = len(alt_algorithms) > 0
        check(results, issues, "T5_1_alternative_algorithms", found_alts, {
            "query": "RRF reciprocal rank fusion BM25 approximate nearest neighbor HNSW",
            "result_count": count,
            "alternatives": alt_algorithms[:3],
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not find alternative algorithms")
        log(test_id, f"T5.1: {count} results, {len(alt_algorithms)} algorithm alternatives found")
        if found_alts:
            note_adoption(journal,
                f"found {len(alt_algorithms)} algorithm alternatives (RRF/BM25/HNSW) via concept search — these span multiple files and naming conventions",
                "positive")
        else:
            note_adoption(journal,
                "no algorithm alternatives surfaced — agent would need domain knowledge to know what to grep for",
                "neutral")
    except Exception as e:
        check(results, issues, "T5_1_alternative_algorithms", False, fail_msg=str(e))

    # ── T5.2: Library/tool alternatives ──────────────────────────────
    log(test_id, "T5.2: Alternative libraries and tools")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="SentenceTransformer embedding model vector search LanceDB PostgreSQL pgvector AlloyDB", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        lib_alts = [
            {"file": res.get("file_path", ""), "snippet": res.get("content", "")[:120]}
            for res in results_list[:5]
            if any(kw in res.get("content", "").lower() + res.get("file_path", "").lower()
                   for kw in ["lancedb", "pgvector", "alloydb", "sentence", "embedding"])
        ]
        found_libs = len(lib_alts) > 0
        check(results, issues, "T5_2_library_alternatives", found_libs, {
            "query": "SentenceTransformer embedding model vector search LanceDB pgvector AlloyDB",
            "result_count": count,
            "library_alts": lib_alts[:3],
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not find library alternatives")
        log(test_id, f"T5.2: {count} results, {len(lib_alts)} library alternatives found")
    except Exception as e:
        check(results, issues, "T5_2_library_alternatives", False, fail_msg=str(e))

    # ═══════════════════════════════════════════════════════════════════
    # T6: Estimate Impact
    # ═══════════════════════════════════════════════════════════════════

    # ── T6.1: Impact estimation - IDF reranking ───────────────────────
    log(test_id, "T6.1: Impact of IDF-weighted reranking on latency")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="IDF weighted reranking score boost normalization RRF k=30 dual_source_bonus", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        rerank_info = [
            {"file": res.get("file_path", ""), "snippet": res.get("content", "")[:150]}
            for res in results_list[:5]
            if any(kw in res.get("content", "").lower() + res.get("file_path", "").lower()
                   for kw in ["idf", "rerank", "rrf", "score", "boost"])
        ]
        found_rerank = len(rerank_info) > 0
        check(results, issues, "T6_1_impact_estimation", found_rerank, {
            "query": "IDF weighted reranking score boost normalization RRF",
            "result_count": count,
            "rerank_impact": rerank_info[:3],
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not find reranking impact information")
        log(test_id, f"T6.1: {count} results, {len(rerank_info)} reranking files found")
    except Exception as e:
        check(results, issues, "T6_1_impact_estimation", False, fail_msg=str(e))

    # ── T6.2: Implementation priority ────────────────────────────────
    log(test_id, "T6.2: Identify quick wins - index optimization, connection pooling")
    try:
        r, t = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="index optimization vector index creation maintenance HNSW IVF performance improvement", limit=10,
        )
        results_list = r.get("results", [])
        count = len(results_list)
        quick_wins = [
            {"file": res.get("file_path", ""), "snippet": res.get("content", "")[:150]}
            for res in results_list[:5]
            if any(kw in res.get("content", "").lower() + res.get("file_path", "").lower()
                   for kw in ["index", "optimize", "performance", "fast", "speed"])
        ]
        found_wins = len(quick_wins) > 0
        check(results, issues, "T6_2_priority_matrix", found_wins, {
            "query": "index optimization vector HNSW IVF performance improvement",
            "result_count": count,
            "quick_wins": quick_wins[:3],
            "elapsed_s": round(t, 2),
        }, fail_msg="Could not identify quick wins")
        log(test_id, f"T6.2: {count} results, {len(quick_wins)} quick win opportunities found")
    except Exception as e:
        check(results, issues, "T6_2_priority_matrix", False, fail_msg=str(e))

    # ── Additional: Search latency measurement ────────────────────────
    log(test_id, "T_latency: Measure actual search latency baseline")
    latency_times = []
    latency_queries = [
        "hybrid search vector FTS combine",
        "performance bottleneck slow query",
        "caching optimization batch processing",
    ]
    try:
        for q in latency_queries:
            r, t = await call_tool(
                search_knowledge, services=services, session_id=session_id,
                query=q, limit=5,
            )
            latency_times.append(round(t, 3))
        avg_latency = sum(latency_times) / len(latency_times)
        max_latency = max(latency_times)
        latency_ok = avg_latency < 30.0  # generous threshold for AlloyDB overhead
        check(results, issues, "T_latency_baseline", latency_ok, {
            "queries_tested": len(latency_queries),
            "latency_seconds": latency_times,
            "avg_latency_s": round(avg_latency, 3),
            "max_latency_s": round(max_latency, 3),
        }, severity="HIGH", fail_msg=f"Search latency too high: avg={avg_latency:.1f}s")
        log(test_id, f"T_latency: avg={avg_latency:.2f}s, max={max_latency:.2f}s")
        if avg_latency < 5.0:
            note_adoption(journal,
                f"latency baseline measured at {avg_latency:.0f}s avg — acceptable for background investigation queries",
                "positive")
        elif avg_latency < 15.0:
            note_adoption(journal,
                f"latency baseline measured at {avg_latency:.0f}s avg — search works but is slower than local grep for simple queries",
                "neutral")
        else:
            note_adoption(journal,
                f"latency baseline measured at {avg_latency:.0f}s avg — too slow for interactive perf investigation",
                "negative")
    except Exception as e:
        check(results, issues, "T_latency_baseline", False, fail_msg=str(e))

    # ── Additional: Entity-based analysis of search service ───────────
    log(test_id, "T_entity: Analyze SearchService entity")
    try:
        r, t = await call_tool(
            understand_entity, services=services, session_id=session_id,
            entity="SearchService",
        )
        entity_found = bool(r.get("entity") or r.get("name") or r.get("results"))
        check(results, issues, "T_entity_search_service", entity_found, {
            "entity": "SearchService",
            "found": entity_found,
            "response_time_s": round(t, 2),
            "response_keys": list(r.keys())[:8],
        }, fail_msg="SearchService entity not found")
        log(test_id, f"T_entity: SearchService found={entity_found}, elapsed={t:.2f}s")
        if entity_found:
            note_adoption(journal,
                f"SearchService entity found and analyzed in {t:.0f}s — instant component understanding",
                "positive")
        else:
            note_adoption(journal,
                "entity lookup failed for SearchService — agent would need to manually trace code",
                "negative")
    except Exception as e:
        check(results, issues, "T_entity_search_service", False, fail_msg=str(e))

    # ── Honest assessment: perf investigation overhead ──────────────────
    note_adoption(journal,
        "ai surfaces performance-related code across multiple files but cannot measure actual runtime "
        "performance — the agent still needs profiling tools (cProfile, py-spy) for real bottleneck identification",
        "neutral")

    # ── Finalize ──────────────────────────────────────────────────────
    elapsed = time.time() - t_start
    summary = summarize(test_id, slug, results, issues, elapsed, project_id, adoption_journal=journal)
    write_results(output_dir, summary)
    log(test_id, f"Done. {summary['pass_rate']} passed in {elapsed:.1f}s")
    return summary
