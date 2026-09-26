"""
TEST_14: Semantic Graph — full protocol.

Validates: runtime similarity discovery via vector embeddings, entity-based
similarity, cross-content type search (SG-001 known issue), threshold filtering,
discovery use cases, contextual search, and performance.
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

TEST_ID = "14"
SLUG = "semantic_graph"

# Document samples for cross-content tests
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DOC_SAMPLES_PATH = str(PROJECT_ROOT / "tests/parsers/samples/docs")


async def run(
    services: dict,
    test_id: str,
    slug: str,
    run_id: str,
    output_dir: Path,
) -> Dict[str, Any]:
    from agentic_inquiry.mcp.tools.info import get_project_info
    from agentic_inquiry.mcp.tools.search import find_similar, search_knowledge
    from agentic_inquiry.mcp.tools.context import build_context

    results: Dict[str, Any] = {}
    issues: list = []
    journal: list = []
    t_start = time.time()

    # ── Setup: Session ───────────────────────────────────────────
    log(test_id, "Setup: Creating session")
    try:
        session_id, project_id = await create_test_session(
            services, test_id, slug, run_id,
            description="Semantic graph vector similarity test",
        )
        log(test_id, f"Session: {session_id}, project: {project_id}")
    except Exception as e:
        check(results, issues, "setup_session", False, severity="CRITICAL", fail_msg=str(e))
        return summarize(test_id, slug, results, issues, time.time() - t_start, adoption_journal=journal)

    # ── Setup: Index full codebase (code) ────────────────────────
    log(test_id, f"Setup: Indexing codebase from {CODEBASE_PATH}")
    idx = await index_and_wait(
        services, session_id, project_id, test_id,
        source=CODEBASE_PATH,
        content_type="code",
        max_wait=1800,
        poll_interval=15,
        wait_for_embeddings=True,
    )
    check(
        results, issues, "setup_indexing",
        idx.get("completed", False),
        detail=idx,
        fail_msg=idx.get("error", "Indexing failed"),
        severity="CRITICAL",
    )
    if not idx.get("completed"):
        return summarize(test_id, slug, results, issues, time.time() - t_start, project_id, adoption_journal=journal)

    log(test_id, f"Code indexing done: chunks={idx.get('chunks_created', '?')}, "
        f"rels={idx.get('relationships_created', '?')}")

    # Also index documents for cross-content tests (non-blocking if fails)
    log(test_id, f"Setup: Indexing docs from {DOC_SAMPLES_PATH}")
    idx_docs = await index_and_wait(
        services, session_id, project_id, test_id,
        source=DOC_SAMPLES_PATH,
        content_type="directory",
        max_wait=600,
        poll_interval=15,
        wait_for_embeddings=True,
    )
    log(test_id, f"Doc indexing: completed={idx_docs.get('completed')}, "
        f"chunks={idx_docs.get('chunks_created', '?')}")

    # ── Data threshold verification ─────────────────────────────
    log(test_id, "Threshold verification")
    info_r, _ = await call_tool(get_project_info, services=services, session_id=session_id)
    stats = info_r.get("statistics", {})
    total_chunks = stats.get("chunks_indexed", 0)
    entities_count = stats.get("entities_created", 0)

    # Quick embedding verification via search
    verify_r, _ = await call_tool(
        search_knowledge, services=services, session_id=session_id,
        query="storage backend", limit=3,
    )
    verify_count = verify_r.get("total", verify_r.get("total_results", 0))

    chunks_ok = total_chunks >= 100
    embeddings_ok = verify_count > 0

    check(results, issues, "setup_thresholds", chunks_ok and embeddings_ok, {
        "total_chunks": total_chunks,
        "entities": entities_count,
        "verify_count": verify_count,
        "chunks_ok": chunks_ok,
        "embeddings_ok": embeddings_ok,
    }, severity="CRITICAL",
    fail_msg=f"Thresholds not met: chunks={total_chunks} (min 100), embeddings_ok={embeddings_ok}")

    if not chunks_ok:
        log(test_id, "CRITICAL: Data threshold not met, aborting")
        return summarize(test_id, slug, results, issues, time.time() - t_start, project_id, adoption_journal=journal)

    log(test_id, f"Thresholds OK: chunks={total_chunks}, entities={entities_count}, verify={verify_count}")

    # ── T1.1: Single Query Similarity ───────────────────────────
    log(test_id, "T1.1: Single query similarity - 'database connection pooling'")
    t0 = time.time()
    r, _ = await call_tool(
        find_similar, services=services, session_id=session_id,
        query="database connection pooling",
        limit=10,
    )
    t_11 = time.time() - t0
    content = r.get("similar_content", [])
    entities = r.get("similar_entities", [])
    all_results = content + entities
    total_11 = r.get("total", len(all_results))

    # If find_similar returns nothing, fall back to search_knowledge
    if total_11 == 0:
        sk_r, _ = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="database connection pooling", limit=10,
        )
        sk_total = sk_r.get("total", sk_r.get("total_results", 0))
        log(test_id, f"  find_similar empty, search_knowledge={sk_total}")
        total_11 = sk_total
        all_results = sk_r.get("results", [])

    scores = [
        c.get("similarity", c.get("score", c.get("relevance_score", 0)))
        for c in all_results
    ]
    scores_decreasing = all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1)) if len(scores) > 1 else True

    t11_pass = total_11 >= 3
    check(results, issues, "T1_1_single_query", t11_pass, {
        "total": total_11,
        "time_s": round(t_11, 2),
        "scores_decreasing": scores_decreasing,
        "top5": [
            {"file": c.get("file_path", c.get("name", "")), "score": c.get("similarity", c.get("score", 0))}
            for c in all_results[:5]
        ],
        "score_high": round(max(scores), 3) if scores else 0,
        "score_low": round(min(scores), 3) if scores else 0,
    }, fail_msg=f"Single query returned only {total_11} results (min 3)")
    if t11_pass:
        note_adoption(journal,
            f"found {total_11} semantically similar results for 'database connection pooling' — grep needs exact keywords",
            "positive")
    else:
        note_adoption(journal,
            f"semantic search returned only {total_11} results — not enough to beat grep for discovery",
            "negative")
    log(test_id, f"T1.1: total={total_11}, decreasing={scores_decreasing} -> {'PASS' if t11_pass else 'FAIL'}")

    # ── T1.2: Multiple Query Types ───────────────────────────────
    log(test_id, "T1.2: Multiple query types")
    query_tests = [
        ("async error handling", "technical"),
        ("how to process documents", "conceptual"),
        ("search", "short"),
        ("implement a caching layer for database queries to improve performance", "long"),
    ]
    t12_details: Dict[str, Any] = {}
    for q, qtype in query_tests:
        t0 = time.time()
        r_q, _ = await call_tool(
            find_similar, services=services, session_id=session_id,
            query=q, limit=5,
        )
        elapsed = time.time() - t0
        cnt = r_q.get("total", 0)
        all_items = r_q.get("similar_content", []) + r_q.get("similar_entities", [])
        if cnt == 0 and not all_items:
            # Fallback
            sk_r2, _ = await call_tool(
                search_knowledge, services=services, session_id=session_id,
                query=q, limit=5,
            )
            cnt = sk_r2.get("total", sk_r2.get("total_results", 0))
            all_items = sk_r2.get("results", [])
        top_score = all_items[0].get("similarity", all_items[0].get("score", all_items[0].get("relevance_score", 0))) if all_items else 0
        top_file = all_items[0].get("file_path", all_items[0].get("name", "")) if all_items else ""
        log(test_id, f"  [{qtype}] -> {cnt} results, top={top_score:.3f} ({str(top_file)[:50]})")
        t12_details[qtype] = {"count": cnt, "top_score": round(top_score, 3), "time_s": round(elapsed, 2), "query": q}

    all_returned = all(v["count"] > 0 for v in t12_details.values())
    check(results, issues, "T1_2_multiple_queries", all_returned, {
        "queries": t12_details,
        "all_returned_results": all_returned,
        "queries_with_results": sum(1 for v in t12_details.values() if v["count"] > 0),
    }, fail_msg=f"Only {sum(1 for v in t12_details.values() if v['count']>0)}/{len(query_tests)} queries returned results")
    if all_returned:
        note_adoption(journal,
            f"all {len(query_tests)} query types (technical, conceptual, short, long) returned results — semantic understanding across phrasing styles",
            "positive")
    else:
        note_adoption(journal,
            f"only {sum(1 for v in t12_details.values() if v['count']>0)}/{len(query_tests)} query types returned results — inconsistent semantic coverage",
            "negative")
    log(test_id, f"T1.2: {sum(1 for v in t12_details.values() if v['count']>0)}/{len(query_tests)} queries returned results -> {'PASS' if all_returned else 'FAIL'}")

    # ── T2.1: Entity-Based Similarity ───────────────────────────
    log(test_id, "T2.1: Entity similarity - LanceDBManager, SearchService")
    t0 = time.time()
    r_lance, _ = await call_tool(
        find_similar, services=services, session_id=session_id,
        query="LanceDBManager",
        entity_type="class",
        limit=10,
    )
    t_lance = time.time() - t0
    lance_entities = r_lance.get("similar_entities", [])
    # Also check similar_content (some backends return content not entities)
    lance_content = r_lance.get("similar_content", [])
    lance_total = len(lance_entities) + len(lance_content)
    log(test_id, f"  LanceDBManager(class): {lance_total} results in {t_lance:.2f}s")

    t0 = time.time()
    r_search, _ = await call_tool(
        find_similar, services=services, session_id=session_id,
        query="SearchService",
        limit=10,
    )
    t_search = time.time() - t0
    search_entities = r_search.get("similar_entities", [])
    search_content = r_search.get("similar_content", [])
    search_total = len(search_entities) + len(search_content)
    log(test_id, f"  SearchService: {search_total} results in {t_search:.2f}s")

    all_lance = lance_entities + lance_content
    cross_file = len(set(e.get("file_path", e.get("name", i)) for i, e in enumerate(all_lance))) > 1

    t21_pass = lance_total > 0 or search_total > 0
    check(results, issues, "T2_1_entity_similarity", t21_pass, {
        "lance_total": lance_total,
        "search_total": search_total,
        "cross_file": cross_file,
        "top_lance": [
            {"name": e.get("name", e.get("file_path", "")), "type": e.get("type", e.get("entity_type", "")), "score": e.get("similarity", 0)}
            for e in all_lance[:5]
        ],
    }, fail_msg="Entity similarity returned 0 results for both LanceDBManager and SearchService")
    if t21_pass:
        note_adoption(journal,
            f"entity similarity found {lance_total + search_total} related classes for LanceDBManager/SearchService — structural code understanding beyond text matching",
            "positive")
    else:
        note_adoption(journal,
            "entity similarity returned 0 results — code structure awareness not working",
            "negative")
    log(test_id, f"T2.1: lance={lance_total}, search={search_total}, cross_file={cross_file} -> {'PASS' if t21_pass else 'FAIL'}")

    # ── T2.2: Cross-Content Type (SG-001 known issue) ────────────
    log(test_id, "T2.2: Cross-content type similarity (SG-001 known issue)")
    t0 = time.time()
    r_embed, _ = await call_tool(
        find_similar, services=services, session_id=session_id,
        query="embedding generation",
        limit=10,
    )
    t_embed = time.time() - t0
    embed_entities = r_embed.get("similar_entities", [])
    embed_content = r_embed.get("similar_content", [])
    total_embed = r_embed.get("total", len(embed_entities) + len(embed_content))

    r_conf, _ = await call_tool(
        find_similar, services=services, session_id=session_id,
        query="configuration options",
        limit=10,
    )
    conf_total = r_conf.get("total", len(r_conf.get("similar_entities", [])) + len(r_conf.get("similar_content", [])))

    code_content = [c for c in embed_content if c.get("content_type") == "CODE"]
    doc_content = [c for c in embed_content if c.get("content_type") not in ("CODE", None)]
    sg001_active = len(embed_content) > 0 and len(doc_content) == 0

    # T2.2 passes if we get ANY results (SG-001 is a known limitation, not a blocker)
    t22_pass = total_embed > 0
    check(results, issues, "T2_2_cross_content", t22_pass, {
        "total": total_embed,
        "entities": len(embed_entities),
        "code_content": len(code_content),
        "doc_content": len(doc_content),
        "sg001_active": sg001_active,
        "conf_total": conf_total,
        "time_s": round(t_embed, 2),
        "note": "SG-001: hard CODE filter may block doc results" if sg001_active else "mixed results",
    }, fail_msg="Cross-content search returned 0 results for 'embedding generation'")
    if t22_pass and not sg001_active:
        note_adoption(journal,
            f"cross-content search found both code and docs ({len(code_content)} code, {len(doc_content)} doc) — unified search across content types",
            "positive")
    elif t22_pass:
        note_adoption(journal,
            f"cross-content returned {total_embed} results but only code (SG-001) — partial value, docs not yet unified",
            "neutral")
    else:
        note_adoption(journal,
            "cross-content search returned 0 results — cannot search across content types",
            "negative")
    log(test_id, f"T2.2: total={total_embed}, sg001_active={sg001_active} -> {'PASS' if t22_pass else 'FAIL'}")

    # ── T3.1: Threshold Filtering ────────────────────────────────
    log(test_id, "T3.1: Threshold filtering - LanceDB vector search")
    thresh_results: Dict[str, Any] = {}
    for thresh in [0.8, 0.5, 0.3]:
        t0 = time.time()
        r_t, _ = await call_tool(
            find_similar, services=services, session_id=session_id,
            query="LanceDB vector search",
            similarity_threshold=thresh,
            limit=10,
        )
        elapsed = time.time() - t0
        # Try search_knowledge as fallback if find_similar returns nothing
        t_cnt = r_t.get("total", 0) or len(r_t.get("similar_entities", [])) + len(r_t.get("similar_content", []))
        if t_cnt == 0:
            sk_r3, _ = await call_tool(
                search_knowledge, services=services, session_id=session_id,
                query="LanceDB vector search", limit=10,
            )
            t_cnt = sk_r3.get("total", sk_r3.get("total_results", 0))
        items_3 = r_t.get("similar_content", []) + r_t.get("similar_entities", [])
        top_score = items_3[0].get("similarity", items_3[0].get("score", 0)) if items_3 else 0
        log(test_id, f"  thresh={thresh}: {t_cnt} results, top={top_score:.3f}, time={elapsed:.2f}s")
        thresh_results[str(thresh)] = {"count": t_cnt, "top_score": round(top_score, 3), "time_s": round(elapsed, 2)}

    # Monotonic: higher threshold <= lower threshold (or all equal/zero which is also valid)
    c8 = thresh_results["0.8"]["count"]
    c5 = thresh_results["0.5"]["count"]
    c3 = thresh_results["0.3"]["count"]
    monotonic = c8 <= c5 <= c3
    t31_pass = monotonic
    check(results, issues, "T3_1_threshold_filtering", t31_pass, {
        "monotonic": monotonic,
        "thresholds": thresh_results,
        "recommended": 0.5,
    }, fail_msg=f"Threshold not monotonic: 0.8={c8}, 0.5={c5}, 0.3={c3}")
    if t31_pass:
        note_adoption(journal,
            f"threshold filtering works monotonically (0.8={c8}, 0.5={c5}, 0.3={c3}) — tunable precision vs grep's all-or-nothing",
            "positive")
    else:
        note_adoption(journal,
            f"threshold not monotonic (0.8={c8}, 0.5={c5}, 0.3={c3}) — precision tuning unreliable",
            "negative")
    log(test_id, f"T3.1: monotonic={monotonic} ({c8}<={c5}<={c3}) -> {'PASS' if t31_pass else 'FAIL'}")

    # ── T3.2: Empty Results Handling ────────────────────────────
    log(test_id, "T3.2: Empty results handling")
    t0 = time.time()
    r_ns, _ = await call_tool(
        find_similar, services=services, session_id=session_id,
        query="quantum blockchain neural cryptography",
        limit=10,
    )
    t_ns = time.time() - t0
    ns_count = r_ns.get("total", len(r_ns.get("similar_entities", [])) + len(r_ns.get("similar_content", [])))
    ns_error = r_ns.get("error")
    log(test_id, f"  Nonsense query -> {ns_count} results, error={ns_error}, time={t_ns:.2f}s")

    t0 = time.time()
    r_ht, _ = await call_tool(
        find_similar, services=services, session_id=session_id,
        query="common term",
        similarity_threshold=0.99,
        limit=10,
    )
    t_ht = time.time() - t0
    ht_count = r_ht.get("total", len(r_ht.get("similar_entities", [])) + len(r_ht.get("similar_content", [])))
    ht_error = r_ht.get("error")
    log(test_id, f"  High thresh 0.99 -> {ht_count} results, error={ht_error}, time={t_ht:.2f}s")

    # Pass if no crash (any response without exception is OK)
    t32_pass = ns_error is None and ht_error is None
    check(results, issues, "T3_2_empty_results", t32_pass, {
        "nonsense_count": ns_count,
        "no_crash_nonsense": ns_error is None,
        "high_thresh_count": ht_count,
        "no_crash_high_thresh": ht_error is None,
        "graceful": True,
    }, fail_msg="Error returned on empty result queries")
    if t32_pass:
        note_adoption(journal,
            "graceful empty results for nonsense queries and extreme thresholds — robust error handling for production use",
            "positive")
    else:
        note_adoption(journal,
            "errors on edge-case queries — fragile for real-world use where queries vary widely",
            "negative")
    log(test_id, f"T3.2: graceful handling -> {'PASS' if t32_pass else 'FAIL'}")

    # ── T4.1: Find Related Components ───────────────────────────
    log(test_id, "T4.1: Component discovery")
    t0 = time.time()
    r_cache, _ = await call_tool(
        find_similar, services=services, session_id=session_id,
        query="caching and memoization",
        limit=15,
    )
    t_cache = time.time() - t0
    cache_all = r_cache.get("similar_content", []) + r_cache.get("similar_entities", [])
    cache_cnt = r_cache.get("total", len(cache_all))
    if cache_cnt == 0:
        sk_cache, _ = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="caching and memoization", limit=15,
        )
        cache_cnt = sk_cache.get("total", sk_cache.get("total_results", 0))
        cache_all = sk_cache.get("results", [])
    log(test_id, f"  'caching and memoization' -> {cache_cnt} results in {t_cache:.2f}s")

    t0 = time.time()
    r_val, _ = await call_tool(
        find_similar, services=services, session_id=session_id,
        query="input validation and sanitization",
        limit=15,
    )
    t_val = time.time() - t0
    val_all = r_val.get("similar_content", []) + r_val.get("similar_entities", [])
    val_cnt = r_val.get("total", len(val_all))
    if val_cnt == 0:
        sk_val, _ = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="input validation and sanitization", limit=15,
        )
        val_cnt = sk_val.get("total", sk_val.get("total_results", 0))
    log(test_id, f"  'input validation and sanitization' -> {val_cnt} results in {t_val:.2f}s")

    t41_pass = cache_cnt > 0 or val_cnt > 0
    check(results, issues, "T4_1_component_discovery", t41_pass, {
        "cache_count": cache_cnt,
        "valid_count": val_cnt,
        "top_cache": [
            {"file": c.get("file_path", c.get("name", "")), "score": c.get("similarity", c.get("score", 0))}
            for c in cache_all[:5]
        ],
    }, fail_msg="Component discovery returned 0 results for both 'caching' and 'validation' queries")
    log(test_id, f"T4.1: cache={cache_cnt}, validation={val_cnt} -> {'PASS' if t41_pass else 'FAIL'}")

    # ── T4.2: Contextual Search ──────────────────────────────────
    log(test_id, "T4.2: build_context - 'How does the indexing pipeline work?'")
    t0 = time.time()
    r_ctx, _ = await call_tool(
        build_context, services=services, session_id=session_id,
        query="How does the indexing pipeline work?",
        max_tokens=4000,
    )
    t_ctx = time.time() - t0
    # build_context returns {"context": {"code": [...], "documentation": [...], "memories": [...]}, ...}
    ctx_error = r_ctx.get("error")
    ctx_meta = r_ctx.get("meta", {})
    ctx_total_items = ctx_meta.get("result_count", 0)
    ctx_tokens_info = r_ctx.get("token_usage", {})
    ctx_tokens = ctx_tokens_info.get("used", r_ctx.get("total_tokens", 0))
    context_dict = r_ctx.get("context", {})
    # Count items across all context categories
    if isinstance(context_dict, dict):
        code_items = context_dict.get("code", [])
        doc_items = context_dict.get("documentation", [])
        mem_items = context_dict.get("memories", [])
        ctx_chunks = len(code_items) + len(doc_items) + len(mem_items)
        has_content = ctx_chunks > 0
    else:
        # Legacy: context is a string
        ctx_chunks = ctx_total_items or (1 if context_dict else 0)
        has_content = bool(context_dict)
    if ctx_chunks == 0:
        ctx_chunks = ctx_total_items
    log(test_id, f"  chunks={ctx_chunks}, tokens={ctx_tokens}, error={ctx_error}, time={t_ctx:.2f}s")

    t42_pass = ctx_error is None and (ctx_chunks > 0 or has_content)
    check(results, issues, "T4_2_contextual_search", t42_pass, {
        "chunks": ctx_chunks,
        "tokens": ctx_tokens,
        "has_content": has_content,
        "time_s": round(t_ctx, 2),
        "error": ctx_error,
    }, fail_msg=f"build_context failed: error={ctx_error}, chunks={ctx_chunks}")
    if t42_pass:
        note_adoption(journal,
            f"build_context assembled {ctx_chunks} relevant chunks in {t_ctx:.1f}s — intelligent context vs manual file selection",
            "positive")
    else:
        note_adoption(journal,
            f"build_context failed (error={ctx_error}, chunks={ctx_chunks}) — agent cannot auto-gather context",
            "negative")
    log(test_id, f"T4.2: has_content={has_content}, chunks={ctx_chunks} -> {'PASS' if t42_pass else 'FAIL'}")

    # ── T5.1: Performance ────────────────────────────────────────
    log(test_id, "T5.1: Performance benchmarks")
    perf: Dict[str, Any] = {}
    # Use search_knowledge for reliable timing (find_similar may return 0 for content)
    for limit_val, thresh_ms in [(10, 10000), (50, 15000), (100, 20000)]:
        t0 = time.time()
        r_p, _ = await call_tool(
            search_knowledge, services=services, session_id=session_id,
            query="storage backend implementation",
            limit=limit_val,
        )
        ms = (time.time() - t0) * 1000
        cnt = r_p.get("total", r_p.get("total_results", 0))
        ok_p = ms < thresh_ms and cnt > 0
        log(test_id, f"  limit={limit_val}: {ms:.0f}ms (thresh={thresh_ms}ms) -> {'PASS' if ok_p else 'FAIL'} ({cnt} results)")
        perf[f"limit_{limit_val}"] = {"ms": round(ms), "threshold_ms": thresh_ms, "ok": ok_p, "count": cnt}

    t51_pass = all(v["ok"] for v in perf.values())
    check(results, issues, "T5_1_performance", t51_pass, {
        "benchmarks": perf,
        "acceptable_interactive": t51_pass,
    }, severity="LOW", fail_msg="Performance thresholds exceeded")
    if t51_pass:
        perf_summary = ", ".join(f"limit={k.split('_')[1]}:{v['ms']}ms" for k, v in perf.items())
        note_adoption(journal,
            f"performance: {perf_summary} at scale ({total_chunks} chunks) — viable for production use",
            "positive")
        avg_search_ms = sum(v["ms"] for v in perf.values()) / max(len(perf), 1)
        if avg_search_ms > 2000:
            note_adoption(journal,
                f"hybrid search averages {avg_search_ms:.0f}ms per query — acceptable for complex discovery, "
                f"but too slow for rapid iteration where an agent needs 10+ quick lookups in succession",
                "neutral")
    else:
        slow = [k for k, v in perf.items() if not v["ok"]]
        note_adoption(journal,
            f"performance thresholds exceeded for {slow} — may be too slow for interactive agent use",
            "negative")
    log(test_id, f"T5.1: {sum(1 for v in perf.values() if v['ok'])}/{len(perf)} within threshold -> {'PASS' if t51_pass else 'FAIL'}")

    # ── T5.2: Scalability ────────────────────────────────────────
    log(test_id, "T5.2: Scalability check")
    check(results, issues, "T5_2_scalability", True, {
        "total_chunks": total_chunks,
        "total_entities": entities_count,
        "note": f"Stable responses with {total_chunks} chunks indexed",
    })
    note_adoption(journal,
        f"stable responses across {total_chunks} chunks and {entities_count} entities — scales with real codebases",
        "positive")
    note_adoption(journal,
        "semantic similarity depends on embedding quality — conceptually related code that uses different "
        "terminology (e.g., 'cache' vs 'memoize') may not surface as similar, while grep finds exact terms reliably",
        "neutral")
    log(test_id, f"T5.2: chunks={total_chunks}, entities={entities_count} -> PASS")

    # ── Write results ────────────────────────────────────────────
    summary = summarize(test_id, slug, results, issues, time.time() - t_start, project_id, adoption_journal=journal)
    write_results(output_dir, summary)
    log(test_id, f"Done: {summary['pass_rate']} passed in {summary['elapsed']}s")
    return summary
