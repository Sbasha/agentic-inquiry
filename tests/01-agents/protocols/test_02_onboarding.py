"""
TEST_02: Onboarding to a New Codebase — full protocol.

Cold start: index target codebase from scratch, then test onboarding tools.
Target: command_iq (TypeScript monorepo, ~1138 source files)

Security note: add_knowledge uses os.getcwd() as security root, so we
temporarily change CWD to the parent of the target codebase before indexing.
"""
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .base import (
    call_tool,
    check,
    log,
    note_adoption,
    summarize,
    write_results,
)

TEST_ID = "02"
SLUG = "onboarding"

# Target codebase for cold-start onboarding
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
PROJECTS_DIR = PROJECT_ROOT.parent  # /Users/michael.parcewski/Projects/
TARGET_CODEBASE = str(PROJECTS_DIR / "command_iq")


async def run(
    services: dict,
    test_id: str,
    slug: str,
    run_id: str,
    output_dir: Path,
    target_codebase: str = TARGET_CODEBASE,
) -> Dict[str, Any]:
    from agentic_inquiry.mcp.tools.session import create_session, get_session
    from agentic_inquiry.mcp.tools.knowledge import add_knowledge
    from agentic_inquiry.mcp.tools.search import search_knowledge
    from agentic_inquiry.mcp.tools.memory import save_memory, recall_memories
    from agentic_inquiry.mcp.tools.info import get_project_info, get_server_info
    from agentic_inquiry.mcp.tools.context import build_context

    results: Dict[str, Any] = {}
    issues: list = []
    journal: list = []
    t_start = time.time()
    t_phase_start = t_start

    project_id = f"ai_test{test_id}_{slug}_{run_id}"

    # ── SETUP: Create Session ──────────────────────────────────────
    log(test_id, "SETUP: Creating fresh session (cold start)")
    try:
        r, t = await call_tool(
            create_session,
            services=services,
            project_id=project_id,
            description="Cold-start onboarding test for command_iq codebase",
        )
        session_id = r.get("session_id")
        if not session_id:
            raise RuntimeError(f"Session creation failed: {r.get('error', 'unknown')}")

        # Verify empty index (cold start requirement)
        stats = r.get("statistics", {})
        initial_chunks = stats.get("chunks", 0)
        check(results, issues, "SETUP_create_session", True, {
            "session_id": session_id,
            "project_id": project_id,
            "initial_chunks": initial_chunks,
            "cold_start": initial_chunks == 0,
        })
        log(test_id, f"  Session: {session_id}, chunks: {initial_chunks}")

    except Exception as e:
        check(results, issues, "SETUP_create_session", False, severity="CRITICAL", fail_msg=str(e))
        return summarize(test_id, slug, results, issues, time.time() - t_start, project_id=project_id, adoption_journal=journal)

    # ── TEST 1: Index the codebase ──────────────────────────────────────
    log(test_id, f"T1: Indexing target codebase: {target_codebase}")
    t_index_start = time.time()
    index_elapsed = 0.0
    files_processed = 0
    chunks_created = 0
    entities_created = 0

    try:
        # Temporarily change CWD to parent of target codebase for security validation
        original_cwd = os.getcwd()
        target_path = Path(target_codebase)
        cwd_for_indexing = str(target_path.parent)
        source_for_indexing = target_codebase  # absolute path

        log(test_id, f"  Changing CWD to {cwd_for_indexing} for security validation")
        os.chdir(cwd_for_indexing)

        try:
            idx_result, idx_time = await call_tool(
                add_knowledge,
                services=services,
                session_id=session_id,
                content_type="directory",
                source=source_for_indexing,
                wait_for_completion=True,
                wait_timeout=1800,
                filters={"exclude_patterns": ["node_modules", ".git", "dist", "build", "*.lock", "__pycache__"]},
            )
        finally:
            # Always restore CWD
            os.chdir(original_cwd)

        index_elapsed = time.time() - t_index_start
        index_status = idx_result.get("status", "unknown")
        files_processed = idx_result.get("items_processed", 0)
        chunks_created = idx_result.get("chunks_created", 0)
        entities_created = idx_result.get("entities_created", 0)

        check(results, issues, "T1_1_indexing_completed", index_status == "completed", {
            "status": index_status,
            "files_processed": files_processed,
            "chunks_created": chunks_created,
            "entities_created": entities_created,
            "elapsed_s": round(index_elapsed, 1),
        }, severity="CRITICAL", fail_msg=f"Indexing failed: {idx_result.get('error', index_status)}")

        log(test_id, f"  Indexing: status={index_status}, files={files_processed}, "
                     f"chunks={chunks_created}, entities={entities_created}, "
                     f"elapsed={index_elapsed:.1f}s")

        if index_status == "completed" and chunks_created > 50:
            note_adoption(journal,
                f"indexed {chunks_created} chunks from {files_processed} files in {index_elapsed:.0f}s "
                f"— pre-built searchable knowledge base vs manual file traversal",
                "positive")
            note_adoption(journal,
                f"indexing {chunks_created} chunks took {index_elapsed:.0f}s — significant upfront cost "
                f"before the first useful query; an agent running 'find . -name *.ts | head' gets orientation in <1s",
                "neutral")
        elif index_status != "completed":
            note_adoption(journal,
                f"indexing failed with status={index_status} — agent would fall back to grep immediately",
                "blocker")

        # Verify we have searchable content
        check(results, issues, "T1_2_chunks_created", chunks_created > 50, {
            "chunks_created": chunks_created,
            "threshold": 50,
        }, fail_msg=f"Too few chunks: {chunks_created}")

    except Exception as e:
        check(results, issues, "T1_1_indexing_completed", False, severity="CRITICAL", fail_msg=str(e))
        return summarize(test_id, slug, results, issues, time.time() - t_start, project_id=project_id, adoption_journal=journal)

    # ── TEST 1.1: T1.1 Project Purpose Discovery ────────────────────────
    log(test_id, "T1.1: Project Purpose Discovery")
    t_phase_start = time.time()
    query_count = 0

    try:
        # Query 1: Project overview
        r1, t1 = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="project overview purpose what does this do",
            limit=5,
        )
        q1_results = len(r1.get("results", []))
        query_count += 1

        # Query 2: Features and capabilities
        r2, t2 = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="main application features capabilities description",
            limit=5,
        )
        q2_results = len(r2.get("results", []))
        query_count += 1

        # Query 3: Domain-specific
        r3, t3 = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="agent commands CLI tools workflow automation",
            limit=5,
        )
        q3_results = len(r3.get("results", []))
        query_count += 1

        # Build context for project overview (correct signature: query, not focus+context_type)
        r_ctx, t_ctx = await call_tool(
            build_context,
            services=services,
            session_id=session_id,
            query="project overview and main purpose",
            focus="balanced",
            max_tokens=2000,
        )

        # Extract snippets to understand the project
        all_results = (
            r1.get("results", [])[:2]
            + r2.get("results", [])[:2]
            + r3.get("results", [])[:2]
        )
        snippets = [r.get("content", "")[:200] for r in all_results if r.get("content")]
        combined_text = " ".join(snippets).lower()

        # Infer domain from content
        domain_indicators = {
            "agent/ai": any(w in combined_text for w in ["agent", "ai", "llm", "claude", "openai"]),
            "cli_tool": any(w in combined_text for w in ["cli", "command", "terminal", "shell"]),
            "collaboration": any(w in combined_text for w in ["collab", "team", "workspace", "session"]),
            "typescript": any(w in combined_text for w in ["typescript", "javascript", "tsx", "interface"]),
        }

        total_results = q1_results + q2_results + q3_results
        purpose_ok = total_results >= 3

        check(results, issues, "T1_1_purpose_discovery", purpose_ok, {
            "q1_query": "project overview purpose",
            "q1_results": q1_results,
            "q2_query": "main application features",
            "q2_results": q2_results,
            "q3_query": "agent commands CLI tools",
            "q3_results": q3_results,
            "total_results": total_results,
            "domain_indicators": domain_indicators,
            "context_built": "error" not in r_ctx,
            "queries_used": query_count,
            "phase_elapsed_s": round(time.time() - t_phase_start, 1),
        }, fail_msg=f"Insufficient search results for purpose discovery: {total_results}")

        domains_detected = sum(1 for v in domain_indicators.values() if v)
        if purpose_ok and domains_detected >= 2:
            note_adoption(journal,
                f"discovered project purpose and {domains_detected} domain signals from code semantics "
                f"— grep can't infer 'what does this project do' from scattered source files",
                "positive")
        elif not purpose_ok:
            note_adoption(journal,
                f"purpose discovery returned only {total_results} results — agent would need to read READMEs manually",
                "negative")

    except Exception as e:
        check(results, issues, "T1_1_purpose_discovery", False, fail_msg=str(e))

    # ── TEST 1.2: Technology Stack Identification ────────────────────────
    log(test_id, "T1.2: Technology Stack Identification")
    t_phase_start = time.time()
    try:
        r_tech, t_tech = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="TypeScript dependencies package framework library",
            limit=5,
        )
        r_build, t_build = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="build system pnpm npm vitest jest configuration",
            limit=5,
        )

        tech_results = r_tech.get("results", [])
        build_results = r_build.get("results", [])
        all_tech_text = " ".join(
            [r.get("content", "") for r in tech_results + build_results]
        ).lower()

        tech_indicators = {
            "typescript": "typescript" in all_tech_text or ".ts" in all_tech_text,
            "nodejs": "node" in all_tech_text or "require" in all_tech_text,
            "pnpm": "pnpm" in all_tech_text,
            "vitest": "vitest" in all_tech_text or "jest" in all_tech_text,
        }
        tech_found = sum(1 for v in tech_indicators.values() if v)

        check(results, issues, "T1_2_tech_stack", tech_found >= 2, {
            "tech_results": len(tech_results),
            "build_results": len(build_results),
            "indicators": tech_indicators,
            "tech_found_count": tech_found,
            "phase_elapsed_s": round(time.time() - t_phase_start, 1),
        }, fail_msg=f"Only {tech_found}/4 tech indicators found")

        if tech_found >= 3:
            note_adoption(journal,
                f"identified {tech_found}/4 tech stack indicators via semantic search "
                f"— consolidates what would require grepping package.json, tsconfig, and build files separately",
                "positive")

    except Exception as e:
        check(results, issues, "T1_2_tech_stack", False, fail_msg=str(e))

    # ── TEST 2.1: Directory Structure Mapping ────────────────────────────
    log(test_id, "T2.1: Directory Structure Mapping")
    t_phase_start = time.time()
    try:
        r_struct, t_struct = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="directory structure packages modules organization src",
            limit=8,
        )
        r_tests, t_tests = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="test files spec configuration setup",
            limit=5,
        )

        struct_results = r_struct.get("results", [])
        test_results_list = r_tests.get("results", [])

        # Extract file paths to map structure
        file_paths = [r.get("file_path", "") for r in struct_results + test_results_list if r.get("file_path")]
        dirs_found = set()
        for fp in file_paths:
            parts = Path(fp).parts
            for part in parts:
                if part in ["packages", "scripts", "docs", "tests", "src", "extensions", "requirements"]:
                    dirs_found.add(part)
                    break

        check(results, issues, "T2_1_directory_mapping", len(struct_results) >= 3, {
            "struct_results": len(struct_results),
            "test_results": len(test_results_list),
            "dirs_found": list(dirs_found),
            "file_paths_found": len(file_paths),
            "phase_elapsed_s": round(time.time() - t_phase_start, 1),
        }, fail_msg=f"Insufficient structure info: {len(struct_results)} results")

    except Exception as e:
        check(results, issues, "T2_1_directory_mapping", False, fail_msg=str(e))

    # ── TEST 2.2: Component Identification ────────────────────────────────
    log(test_id, "T2.2: Component Identification")
    t_phase_start = time.time()
    try:
        r_comp1, _ = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="main class module export interface service",
            limit=10,
        )
        r_comp2, _ = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="backend frontend API handler router controller",
            limit=8,
        )

        comp_results = r_comp1.get("results", []) + r_comp2.get("results", [])
        unique_files = list(set(r.get("file_path", "") for r in comp_results if r.get("file_path")))

        check(results, issues, "T2_2_component_identification", len(unique_files) >= 5, {
            "comp_results": len(comp_results),
            "unique_files": len(unique_files),
            "sample_files": unique_files[:5],
            "phase_elapsed_s": round(time.time() - t_phase_start, 1),
        }, fail_msg=f"Only {len(unique_files)} unique component files found")

        if len(unique_files) >= 5:
            note_adoption(journal,
                f"identified {len(unique_files)} distinct component files across the codebase "
                f"— semantic search surfaces related components that aren't co-located in the file tree",
                "positive")
        elif len(unique_files) < 3:
            note_adoption(journal,
                f"only found {len(unique_files)} component files — too few to map the codebase, "
                f"agent would still need to manually browse directories",
                "negative")

    except Exception as e:
        check(results, issues, "T2_2_component_identification", False, fail_msg=str(e))

    # ── TEST 2.3: Architectural Patterns ────────────────────────────────
    log(test_id, "T2.3: Architectural Patterns")
    t_phase_start = time.time()
    try:
        r_arch, _ = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="architecture pattern design layer service dependency injection",
            limit=8,
        )
        r_config, _ = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="configuration environment setup initialization bootstrap",
            limit=5,
        )

        arch_results = r_arch.get("results", [])
        config_results = r_config.get("results", [])
        arch_text = " ".join([r.get("content", "") for r in arch_results]).lower()

        pattern_indicators = {
            "layered": any(w in arch_text for w in ["layer", "service", "repository", "controller"]),
            "event_driven": any(w in arch_text for w in ["event", "emit", "on(", "handler", "listener"]),
            "modular": any(w in arch_text for w in ["module", "package", "export", "import"]),
            "config_driven": len(config_results) > 0,
        }
        patterns_found = sum(1 for v in pattern_indicators.values() if v)

        check(results, issues, "T2_3_architectural_patterns", patterns_found >= 2, {
            "arch_results": len(arch_results),
            "config_results": len(config_results),
            "patterns": pattern_indicators,
            "patterns_found": patterns_found,
            "phase_elapsed_s": round(time.time() - t_phase_start, 1),
        }, fail_msg=f"Only {patterns_found}/4 architectural patterns identified")

    except Exception as e:
        check(results, issues, "T2_3_architectural_patterns", False, fail_msg=str(e))

    # ── TEST 3.1: Main Entry Points ────────────────────────────────────
    log(test_id, "T3.1: Main Entry Points")
    t_phase_start = time.time()
    try:
        r_entry, _ = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="main entry point start server CLI command handler index",
            limit=8,
        )
        r_init, _ = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="initialization startup bootstrap app server listen port",
            limit=5,
        )

        entry_results = r_entry.get("results", [])
        init_results = r_init.get("results", [])
        all_paths = [r.get("file_path", "") for r in entry_results + init_results if r.get("file_path")]

        # Check for typical entry point file names
        entry_indicators = [p for p in all_paths if any(
            name in Path(p).name.lower() for name in ["index", "main", "server", "app", "cli", "entry"]
        )]

        check(results, issues, "T3_1_entry_points", len(entry_results) >= 2, {
            "entry_results": len(entry_results),
            "init_results": len(init_results),
            "entry_files": entry_indicators[:5],
            "phase_elapsed_s": round(time.time() - t_phase_start, 1),
        }, fail_msg=f"Entry points unclear: only {len(entry_results)} results")

    except Exception as e:
        check(results, issues, "T3_1_entry_points", False, fail_msg=str(e))

    # ── TEST 3.2: Request Flow ────────────────────────────────────────
    log(test_id, "T3.2: Request/Command Flow")
    t_phase_start = time.time()
    try:
        r_flow, _ = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="request handler process flow route middleware pipeline",
            limit=8,
        )
        r_cmd, _ = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="command execution run invoke dispatch process",
            limit=5,
        )

        flow_results = r_flow.get("results", [])
        cmd_results = r_cmd.get("results", [])

        check(results, issues, "T3_2_request_flow", len(flow_results) >= 2, {
            "flow_results": len(flow_results),
            "cmd_results": len(cmd_results),
            "phase_elapsed_s": round(time.time() - t_phase_start, 1),
        }, fail_msg=f"Flow unclear: {len(flow_results)} results")

    except Exception as e:
        check(results, issues, "T3_2_request_flow", False, fail_msg=str(e))

    # ── TEST 4.1: Feature Location ────────────────────────────────────
    log(test_id, "T4.1: Feature Location")
    t_phase_start = time.time()
    feature_tests = []

    try:
        # Feature 1: Authentication/Session management
        t_f1 = time.time()
        r_auth, _ = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="authentication session management user token",
            limit=5,
        )
        auth_found = len(r_auth.get("results", [])) > 0
        feature_tests.append({
            "feature": "Authentication/Session",
            "results": len(r_auth.get("results", [])),
            "found": auth_found,
            "elapsed_ms": round((time.time() - t_f1) * 1000),
        })

        # Feature 2: Data storage
        t_f2 = time.time()
        r_data, _ = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="database storage persistence data model schema",
            limit=5,
        )
        data_found = len(r_data.get("results", [])) > 0
        feature_tests.append({
            "feature": "Data Storage",
            "results": len(r_data.get("results", [])),
            "found": data_found,
            "elapsed_ms": round((time.time() - t_f2) * 1000),
        })

        # Feature 3: Error handling
        t_f3 = time.time()
        r_err, _ = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="error handling exception catch throw retry",
            limit=5,
        )
        err_found = len(r_err.get("results", [])) > 0
        feature_tests.append({
            "feature": "Error Handling",
            "results": len(r_err.get("results", [])),
            "found": err_found,
            "elapsed_ms": round((time.time() - t_f3) * 1000),
        })

        found_count = sum(1 for f in feature_tests if f["found"])
        avg_ms = sum(f["elapsed_ms"] for f in feature_tests) / max(len(feature_tests), 1)
        check(results, issues, "T4_1_feature_location", found_count >= 2, {
            "features_tested": len(feature_tests),
            "features_found": found_count,
            "feature_details": feature_tests,
            "phase_elapsed_s": round(time.time() - t_phase_start, 1),
        }, fail_msg=f"Only {found_count}/3 features located")

        if found_count >= 2:
            note_adoption(journal,
                f"located {found_count}/3 features at ~{avg_ms:.0f}ms avg — semantic feature location "
                f"finds auth/storage/error-handling code without knowing file names or patterns",
                "positive")
        else:
            note_adoption(journal,
                f"feature location found only {found_count}/3 features — agent would have to grep manually",
                "negative")

    except Exception as e:
        check(results, issues, "T4_1_feature_location", False, fail_msg=str(e))

    # ── TEST 4.2: Common Utilities ────────────────────────────────────
    log(test_id, "T4.2: Common Utilities")
    t_phase_start = time.time()
    try:
        r_util, _ = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="utility helper logger logging validation constants types",
            limit=8,
        )
        r_types, _ = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="type definition interface enum const export",
            limit=5,
        )

        util_results = r_util.get("results", [])
        type_results = r_types.get("results", [])
        util_files = list(set(
            r.get("file_path", "") for r in util_results + type_results
            if any(w in r.get("file_path", "").lower() for w in ["util", "helper", "type", "constant", "logger"])
        ))

        check(results, issues, "T4_2_utilities", len(util_results) >= 2, {
            "util_results": len(util_results),
            "type_results": len(type_results),
            "utility_files": util_files[:5],
            "phase_elapsed_s": round(time.time() - t_phase_start, 1),
        }, fail_msg=f"Utilities unclear: {len(util_results)} results")

    except Exception as e:
        check(results, issues, "T4_2_utilities", False, fail_msg=str(e))

    # ── TEST 5.1: Store Onboarding Insights ──────────────────────────────
    log(test_id, "T5.1: Storing Onboarding Memories")
    t_phase_start = time.time()
    memories_stored = 0
    memories_attempted = 0

    memory_items = [
        {
            "summary": "command_iq project overview",
            "content": "command_iq is a TypeScript monorepo providing AI agent CLI tooling. "
                       "Uses pnpm workspaces with packages/ directory containing multiple modules. "
                       "Multiple CLI entry points: agent-cli.sh, collab-cli.sh, jam-cli.sh.",
            "importance": 0.9,
            "tags": ["onboarding", "project-overview", "architecture"],
        },
        {
            "summary": "command_iq entry points and CLI structure",
            "content": "Entry points are CLI shell scripts: agent-cli.sh, collab-cli.sh, jam-cli.sh. "
                       "Suggests multiple distinct agent modes. Frontend and backend logs exist separately.",
            "importance": 0.8,
            "tags": ["onboarding", "entry-points", "cli"],
        },
        {
            "summary": "command_iq technology stack",
            "content": "Codebase uses TypeScript with vitest for testing. Build system uses pnpm workspaces. "
                       "packages/ directory contains modular components. Node.js runtime.",
            "importance": 0.8,
            "tags": ["onboarding", "technology-stack", "testing"],
        },
        {
            "summary": "command_iq data storage pattern",
            "content": "Data directory contains checkpoints/ suggesting state persistence for agent sessions. "
                       "Storage pattern appears file-based for agent state.",
            "importance": 0.7,
            "tags": ["onboarding", "data-storage", "architecture"],
        },
        {
            "summary": "command_iq architecture - extensions and docs",
            "content": "docs/ directory for documentation. extensions/ directory suggests plugin/extension "
                       "architecture similar to VS Code extensions. Full-stack application.",
            "importance": 0.7,
            "tags": ["onboarding", "docs", "architecture", "extensions"],
        },
    ]

    for mem in memory_items:
        memories_attempted += 1
        try:
            r_mem, _ = await call_tool(
                save_memory,
                services=services,
                session_id=session_id,
                summary=mem["summary"],
                content=mem["content"],
                importance=mem["importance"],
                tags=mem["tags"],
            )
            if "error" not in r_mem and r_mem.get("memory_id"):
                memories_stored += 1
        except Exception:
            pass

    check(results, issues, "T5_1_memory_storage", memories_stored >= 3, {
        "memories_attempted": memories_attempted,
        "memories_stored": memories_stored,
        "success_rate": f"{memories_stored}/{memories_attempted}",
        "phase_elapsed_s": round(time.time() - t_phase_start, 1),
    }, fail_msg=f"Only {memories_stored}/{memories_attempted} memories stored")

    if memories_stored >= 3:
        note_adoption(journal,
            f"stored {memories_stored} onboarding insights as persistent memory "
            f"— grep has no memory; next session starts from zero without this",
            "positive")
    elif memories_stored == 0:
        note_adoption(journal,
            "memory storage completely failed — no persistent onboarding knowledge, "
            "negating the key advantage over stateless grep",
            "blocker")

    # ── TEST 5.2: Knowledge Retrieval ──────────────────────────────────────
    log(test_id, "T5.2: Knowledge Retrieval")
    t_phase_start = time.time()
    try:
        r_recall1, _ = await call_tool(
            recall_memories,
            services=services,
            session_id=session_id,
            query="onboarding project overview",
            limit=10,
        )
        r_recall2, _ = await call_tool(
            recall_memories,
            services=services,
            session_id=session_id,
            query="architecture entry points CLI",
            limit=5,
        )

        recall1_count = len(r_recall1.get("memories", []))
        recall2_count = len(r_recall2.get("memories", []))
        total_recalled = recall1_count + recall2_count

        check(results, issues, "T5_2_memory_retrieval", total_recalled >= 2, {
            "recall1_query": "onboarding project overview",
            "recall1_results": recall1_count,
            "recall2_query": "architecture entry points",
            "recall2_results": recall2_count,
            "total_recalled": total_recalled,
            "phase_elapsed_s": round(time.time() - t_phase_start, 1),
        }, fail_msg=f"Memory recall insufficient: {total_recalled} total memories recalled")

        if total_recalled >= 2:
            note_adoption(journal,
                f"recalled {total_recalled} stored insights by semantic query "
                f"— agent can resume onboarding across sessions without re-reading the codebase",
                "positive")

    except Exception as e:
        check(results, issues, "T5_2_memory_retrieval", False, fail_msg=str(e))

    # ── TEST 6.1: Comprehension Check ──────────────────────────────────────
    log(test_id, "T6.1: Comprehension Check via Context Building")
    t_phase_start = time.time()
    try:
        r_comp_ctx, t_comp_ctx = await call_tool(
            build_context,
            services=services,
            session_id=session_id,
            query="complete project architecture overview entry points and key components",
            focus="balanced",
            max_tokens=3000,
        )

        ctx_ok = "error" not in r_comp_ctx
        token_usage = r_comp_ctx.get("token_usage", {})
        ctx_tokens = token_usage.get("used", r_comp_ctx.get("token_count", 0))
        context_dict = r_comp_ctx.get("context", {})
        ctx_chunks = (
            len(context_dict.get("code", []))
            + len(context_dict.get("documentation", []))
            + len(context_dict.get("memories", []))
        ) if isinstance(context_dict, dict) else len(r_comp_ctx.get("chunks", []))

        check(results, issues, "T6_1_comprehension_context", ctx_ok and (ctx_tokens > 100 or ctx_chunks > 0), {
            "context_built": ctx_ok,
            "token_count": ctx_tokens,
            "chunks_in_context": ctx_chunks,
            "elapsed_s": round(t_comp_ctx, 2),
            "phase_elapsed_s": round(time.time() - t_phase_start, 1),
        }, fail_msg=f"Context building failed or too sparse: {ctx_tokens} tokens")

    except Exception as e:
        check(results, issues, "T6_1_comprehension_context", False, fail_msg=str(e))

    # ── TEST 6.2: Simulated Task ──────────────────────────────────────
    log(test_id, "T6.2: Simulated Task - Adding a new CLI command")
    t_phase_start = time.time()
    try:
        t_task_start = time.time()

        r_task1, _ = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="command registration CLI command handler add new command",
            limit=8,
        )
        r_task2, _ = await call_tool(
            search_knowledge,
            services=services,
            session_id=session_id,
            query="commands directory list register execute",
            limit=5,
        )

        task_results = r_task1.get("results", []) + r_task2.get("results", [])
        task_files = [r.get("file_path", "") for r in task_results if r.get("file_path")]
        cmd_files = [f for f in task_files if any(
            w in f.lower() for w in ["command", "cmd", "cli", "handler", "router"]
        )]

        task_elapsed = time.time() - t_task_start
        task_success = len(task_results) >= 2

        check(results, issues, "T6_2_simulated_task", task_success, {
            "task": "Where to add a new CLI command",
            "task_results": len(task_results),
            "command_files_found": cmd_files[:5],
            "task_elapsed_s": round(task_elapsed, 1),
            "phase_elapsed_s": round(time.time() - t_phase_start, 1),
        }, fail_msg=f"Could not locate where to add new command: {len(task_results)} results")

        if task_success and cmd_files:
            note_adoption(journal,
                f"located {len(cmd_files)} command-related files in {task_elapsed:.1f}s for 'add new CLI command' task "
                f"— agent gets actionable file list vs grepping for 'command' across thousands of files",
                "positive")
        elif not task_success:
            note_adoption(journal,
                "could not locate where to add a new CLI command — the core onboarding deliverable failed",
                "negative")

    except Exception as e:
        check(results, issues, "T6_2_simulated_task", False, fail_msg=str(e))

    # ── Honest assessment: onboarding cost vs benefit ──────────────────
    total_elapsed = time.time() - t_start
    note_adoption(journal,
        f"total onboarding protocol took {total_elapsed:.0f}s — for a one-time codebase review, "
        f"reading README + directory listing is faster; ai value comes from repeated queries across sessions",
        "neutral")

    # ── Finalize ────────────────────────────────────────────────────
    log(test_id, f"Tests complete in {total_elapsed:.1f}s")

    summary = summarize(test_id, slug, results, issues, total_elapsed, project_id=project_id, adoption_journal=journal)
    summary["target_codebase"] = target_codebase
    summary["indexing_stats"] = {
        "files": files_processed,
        "chunks": chunks_created,
        "entities": entities_created,
        "elapsed_s": round(index_elapsed, 1),
    }
    write_results(output_dir, summary)

    return summary
