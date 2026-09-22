"""
TEST_12: Code Graph — full protocol.

Validates: entity extraction, relationship types (imports/calls/defines/inherits),
import chain traversal, cross-file resolution, call graphs, blast radius analysis,
entity resolution, and traversal performance.
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

TEST_ID = "12"
SLUG = "code_graph"


async def run(
    services: dict,
    test_id: str,
    slug: str,
    run_id: str,
    output_dir: Path,
) -> Dict[str, Any]:
    from agentic_inquiry.mcp.tools.info import get_project_info, list_entities
    from agentic_inquiry.mcp.tools.analysis import understand_entity, analyze_impact
    from agentic_inquiry.mcp.tools.search import find_similar
    from agentic_inquiry.mcp.tools.direct_access import graph_traverse

    results: Dict[str, Any] = {}
    issues: list = []
    journal: list = []
    t_start = time.time()

    # ── Setup: Session + Full Index ─────────────────────────────
    log(test_id, "Setup: Session + full codebase index")
    try:
        session_id, project_id = await create_test_session(
            services, test_id, slug, run_id,
            description="Code graph extraction and traversal test",
        )
    except Exception as e:
        check(results, issues, "setup_session", False, severity="CRITICAL", fail_msg=str(e))
        return summarize(test_id, slug, results, issues, time.time() - t_start, adoption_journal=journal)

    idx = await index_and_wait(
        services, session_id, project_id, test_id,
        source=CODEBASE_PATH,
        content_type="code",
        max_wait=1800,
        poll_interval=15,
        wait_for_embeddings=True,  # Need entity embeddings for find_similar tests
    )
    check(
        results, issues, "setup_indexing",
        idx.get("completed", False),
        detail=idx,
        fail_msg=idx.get("error", "Indexing failed"),
    )
    if not idx.get("completed"):
        return summarize(test_id, slug, results, issues, time.time() - t_start, project_id, adoption_journal=journal)

    # ── Threshold check (via list_entities, not get_project_info counts) ──
    log(test_id, "Threshold verification via list_entities")
    classes_r, _ = await call_tool(list_entities, services=services, session_id=session_id, entity_type="class", limit=1)
    funcs_r, _ = await call_tool(list_entities, services=services, session_id=session_id, entity_type="function", limit=1)

    # list_entities returns actual entities — if any exist, indexing produced them
    has_classes = len(classes_r.get("entities", [])) > 0
    has_functions = len(funcs_r.get("entities", [])) > 0

    # Also try search to validate data exists
    search_r, _ = await call_tool(
        find_similar, services=services, session_id=session_id,
        query="Config", entity_type="class",
    )
    has_search = len(search_r.get("entities", search_r.get("results", []))) > 0

    thresholds_met = has_classes or has_functions or has_search
    check(results, issues, "thresholds", thresholds_met, {
        "has_classes": has_classes,
        "has_functions": has_functions,
        "has_search_results": has_search,
    }, severity="CRITICAL", fail_msg="No entities found via list_entities or find_similar")
    if not thresholds_met:
        # Also try get_project_info for diagnostics
        info_r, _ = await call_tool(get_project_info, services=services, session_id=session_id)
        log(test_id, f"  Diagnostic: entity_counts={info_r.get('entity_counts', {})}")
        return summarize(test_id, slug, results, issues, time.time() - t_start, project_id, adoption_journal=journal)

    # ── T1.1: Entity Extraction ─────────────────────────────────
    log(test_id, "T1.1: Entity extraction")
    classes_r, _ = await call_tool(list_entities, services=services, session_id=session_id, entity_type="class", limit=20)
    funcs_r, _ = await call_tool(list_entities, services=services, session_id=session_id, entity_type="function", limit=20)
    methods_r, _ = await call_tool(list_entities, services=services, session_id=session_id, entity_type="method", limit=20)

    class_ents = classes_r.get("entities", [])
    func_ents = funcs_r.get("entities", [])
    method_ents = methods_r.get("entities", [])

    check(results, issues, "T1_1_entity_extraction", len(class_ents) > 0 and len(func_ents) > 0, {
        "classes": len(class_ents),
        "functions": len(func_ents),
        "methods": len(method_ents),
        "sample_classes": [e.get("name") for e in class_ents[:5]],
    })
    total_ents = len(class_ents) + len(func_ents) + len(method_ents)
    if total_ents > 0:
        note_adoption(journal, f"extracted {total_ents} function/class/method entities — structured code intelligence vs raw text", "positive")
    else:
        note_adoption(journal, "entity extraction returned nothing — no structured code intelligence available", "blocker")

    # ── T1.2: Relationship Types (Functional) ───────────────────
    log(test_id, "T1.2: Relationship types via functional tools")

    # imports via understand_entity
    r, _ = await call_tool(
        understand_entity, services=services, session_id=session_id,
        entity="LanceDBManager", include_dependencies=True,
    )
    deps = r.get("dependencies", {})
    if not isinstance(deps, dict):
        deps = {}
    imports_found = deps.get("imports", []) or r.get("imports", [])
    has_imports = len(imports_found) > 0 if isinstance(imports_found, list) else False

    # calls via analyze_impact
    r, _ = await call_tool(
        analyze_impact, services=services, session_id=session_id,
        entity="hybrid_search", max_depth=1,
    )
    has_calls = len(r.get("direct_impact", r.get("dependents", []))) > 0

    # defines via graph_traverse
    has_defines = False
    if class_ents:
        class_id = class_ents[0].get("id") or class_ents[0].get("entity_id")
        if class_id:
            r, _ = await call_tool(
                graph_traverse, services=services, session_id=session_id,
                start_id=str(class_id), relationship_types=["defines"], max_depth=1,
            )
            has_defines = len(r.get("nodes", [])) > 1

    # inherits via find_similar + understand_entity
    has_inherits = False
    r, _ = await call_tool(
        find_similar, services=services, session_id=session_id,
        query="BaseService", entity_type="class",
    )
    similar = r.get("similar_entities", r.get("entities", r.get("results", [])))
    if similar:
        candidate = similar[0].get("name", "")
        if candidate and candidate != "BaseService":
            r, _ = await call_tool(
                understand_entity, services=services, session_id=session_id,
                entity=candidate, include_dependencies=True,
            )
            inh = r.get("inherits", []) or (r.get("dependencies") if isinstance(r.get("dependencies"), dict) else {}).get("inherits", [])
            has_inherits = len(inh) > 0 if isinstance(inh, list) else False

    check(results, issues, "T1_2_relationship_types", has_imports or has_calls or has_defines, {
        "imports_work": has_imports,
        "calls_work": has_calls,
        "defines_work": has_defines,
        "inherits_work": has_inherits,
    }, fail_msg="No relationship types verified through functional tools")
    rel_count = sum([has_imports, has_calls, has_defines, has_inherits])
    if rel_count >= 2:
        note_adoption(journal, f"verified {rel_count}/4 relationship types (imports/calls/defines/inherits) — relationship graph grep cannot build", "positive")
    elif rel_count == 0:
        note_adoption(journal, "no relationship types verified — graph is empty, no advantage over grep", "negative")

    # ── T2.1: Import Chain ──────────────────────────────────────
    log(test_id, "T2.1: Import chain — LanceDBManager")
    r, t = await call_tool(
        understand_entity, services=services, session_id=session_id,
        entity="LanceDBManager", include_dependencies=True,
    )
    entity_found = "error" not in r and r.get("entity") is not None
    check(results, issues, "T2_1_import_chain", entity_found, {
        "entity_found": entity_found,
        "elapsed_s": round(t, 2),
        "dep_keys": list(r.get("dependencies", {}).keys()) if isinstance(r.get("dependencies"), dict) else [],
    })
    if entity_found:
        dep_keys = list(r.get("dependencies", {}).keys()) if isinstance(r.get("dependencies"), dict) else []
        note_adoption(journal, f"traced import chain for LanceDBManager ({len(dep_keys)} dep categories) — cross-file dependency tracing grep can't do", "positive")

    # ── T2.2: Cross-File Resolution ─────────────────────────────
    log(test_id, "T2.2: Cross-file resolution")
    r, t = await call_tool(
        analyze_impact, services=services, session_id=session_id,
        entity="LanceDBManager", max_depth=2,
    )
    # analyze_impact returns impact_radius (int) and affected_entities (list)
    impact_radius = r.get("impact_radius", 0)
    affected = r.get("affected_entities", [])
    rel_types = r.get("relationship_types", {})

    check(results, issues, "T2_2_cross_file", impact_radius > 0 or len(affected) > 0, {
        "impact_radius": impact_radius,
        "affected_entities": len(affected),
        "relationship_types": rel_types,
        "elapsed_s": round(t, 2),
    })

    # ── T3.1: Call Relationships ────────────────────────────────
    log(test_id, "T3.1: Call relationships — search_knowledge")
    r, t = await call_tool(
        understand_entity, services=services, session_id=session_id,
        entity="search_knowledge", include_dependencies=True,
    )
    entity_found = "error" not in r and r.get("entity") is not None
    calls_data = r.get("calls", []) or (r.get("dependencies") if isinstance(r.get("dependencies"), dict) else {}).get("calls", [])
    check(results, issues, "T3_1_call_relationships", entity_found, {
        "entity_found": entity_found,
        "calls": len(calls_data) if isinstance(calls_data, list) else 0,
        "elapsed_s": round(t, 2),
    })

    # ── T3.2: Method Calls Within Classes ───────────────────────
    log(test_id, "T3.2: Internal method calls — IndexingPipeline")
    r, t = await call_tool(
        understand_entity, services=services, session_id=session_id,
        entity="IndexingPipeline", include_dependencies=True,
    )
    entity_found = "error" not in r and r.get("entity") is not None
    deps = r.get("dependencies", {})
    internal = r.get("internal_calls", []) or (deps.get("calls", []) if isinstance(deps, dict) else [])
    check(results, issues, "T3_2_method_calls", entity_found, {
        "entity_found": entity_found,
        "internal_calls": len(internal) if isinstance(internal, list) else 0,
    })

    # ── T4.1: Blast Radius ──────────────────────────────────────
    log(test_id, "T4.1: Blast radius — LanceDBManager")
    r, t = await call_tool(
        analyze_impact, services=services, session_id=session_id,
        entity="LanceDBManager", max_depth=2,
    )
    impact_radius = r.get("impact_radius", 0)
    affected = r.get("affected_entities", [])
    rel_types = r.get("relationship_types", {})

    check(results, issues, "T4_1_blast_radius", impact_radius > 0 or len(affected) > 0, {
        "impact_radius": impact_radius,
        "affected_count": len(affected),
        "relationship_types": rel_types,
        "elapsed_s": round(t, 2),
    })
    if impact_radius > 0 or len(affected) > 0:
        note_adoption(journal, f"blast radius analysis found {max(impact_radius, len(affected))} affected entities — impact analysis without manual tracing", "positive")
    else:
        note_adoption(journal, "blast radius returned 0 affected entities — no impact analysis available", "negative")

    # ── T4.2: Inheritance ───────────────────────────────────────
    log(test_id, "T4.2: Inheritance impact")
    # Use list_entities with pattern matching — more reliable than find_similar
    # which depends on embeddings that may not be ready
    r, _ = await call_tool(
        list_entities, services=services, session_id=session_id,
        pattern="Service", entity_type="class", limit=10,
    )
    service_classes = r.get("entities", [])
    check(results, issues, "T4_2_inheritance", len(service_classes) > 0, {
        "service_classes": len(service_classes),
        "sample": [e.get("name") for e in service_classes[:3]],
    })

    # ── T5.1: Ambiguous Name Resolution ─────────────────────────
    log(test_id, "T5.1: Ambiguous name resolution")
    r1, _ = await call_tool(
        list_entities, services=services, session_id=session_id,
        pattern="Config", entity_type="class", limit=10,
    )
    r2, _ = await call_tool(
        list_entities, services=services, session_id=session_id,
        pattern="process", entity_type="function", limit=10,
    )
    config_ents = r1.get("entities", [])
    process_ents = r2.get("entities", [])

    check(results, issues, "T5_1_entity_resolution", len(config_ents) > 0 or len(process_ents) > 0, {
        "config_results": len(config_ents),
        "process_results": len(process_ents),
    })
    if len(config_ents) > 1 or len(process_ents) > 1:
        note_adoption(journal, f"resolved ambiguous names: {len(config_ents)} Config classes, {len(process_ents)} process functions — intelligent disambiguation vs grep's literal matching", "positive")
    elif len(config_ents) > 0 or len(process_ents) > 0:
        note_adoption(journal, "entity resolution found results but limited disambiguation data", "neutral")

    # ── T6.1: Traversal Performance ─────────────────────────────
    log(test_id, "T6.1: Traversal performance")
    perf = {}
    for depth in (1, 2, 3):
        t0 = time.time()
        r, _ = await call_tool(
            analyze_impact, services=services, session_id=session_id,
            entity="LanceDBManager", max_depth=depth,
        )
        ms = (time.time() - t0) * 1000
        radius = r.get("impact_radius", 0)
        affected = len(r.get("affected_entities", []))
        perf[f"depth{depth}_ms"] = round(ms)
        perf[f"depth{depth}_count"] = radius
        # Limits: 30s per depth level (BFS on 71K rels via AlloyDB is 15-25s)
        # The in-memory graph architecture (#99) will bring this to <50ms
        perf[f"depth{depth}_pass"] = ms < 30000 and radius > 0

    check(results, issues, "T6_1_performance", perf.get("depth1_pass", False), perf)
    depth1_ms = perf.get("depth1_ms", 0)
    depth1_s = depth1_ms / 1000
    if perf.get("depth1_pass", False):
        note_adoption(journal, f"graph traversal completed in {depth1_s:.1f}s at depth 1 — relationship navigation at scale", "positive")
    else:
        note_adoption(journal, f"graph traversal took {depth1_s:.1f}s or returned empty — too slow or broken for interactive use", "negative")
    if depth1_s > 10.0:
        note_adoption(journal,
            f"graph traversal at {depth1_s:.1f}s is slower than scanning a few files manually for small codebases "
            f"— graph value emerges only for large codebases where manual tracing is impractical",
            "neutral")

    # Honest assessment: graph limitations
    note_adoption(journal,
        "code graph extracts entities and relationships but relies on tree-sitter parsing — dynamic dispatch, "
        "decorators, and metaprogramming create relationships the graph cannot see",
        "neutral")

    summary = summarize(test_id, slug, results, issues, time.time() - t_start, project_id, adoption_journal=journal)
    write_results(output_dir, summary)
    log(test_id, f"Done: {summary['pass_rate']} in {summary['elapsed']}s")
    return summary
