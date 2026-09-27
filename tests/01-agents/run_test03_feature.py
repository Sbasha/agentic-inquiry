"""
Runner for TEST_03 Feature Implementation UAT.

Feature: Add a new CLI command `ai stats` that shows index statistics,
following the pattern of existing CLI commands.
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
for noisy in [
    "httpx",
    "httpcore",
    "asyncio",
    "urllib3",
    "sentence_transformers",
    "transformers",
    "torch",
]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

RUN_ID = "20260320_213916"
PROJECT_ID = f"ai_test03_feature_{RUN_ID}"
OUTPUT_DIR = PROJECT_ROOT / "test_results" / "ai" / RUN_ID / "feature_implementation"
ENV_PATH = str(PROJECT_ROOT / ".agentic-inquiry" / "envs" / "ai-prod" / "config.yaml")
CODEBASE_PATH = str(PROJECT_ROOT)


def ts():
    return time.strftime("%H:%M:%S")


def log(msg: str):
    print(f"[{ts()}] TEST_03: {msg}", flush=True)


async def main():
    from agentic_inquiry.config import Config
    from agentic_inquiry.mcp.factories import create_mcp_services
    from agentic_inquiry.mcp.tools.session import create_session
    from agentic_inquiry.mcp.tools.knowledge import add_knowledge
    from agentic_inquiry.mcp.tools.info import get_project_info
    from agentic_inquiry.mcp.tools.search import search_knowledge
    from agentic_inquiry.mcp.tools.memory import save_memory, recall_memories
    from agentic_inquiry.mcp.tools.analysis import analyze_impact

    results = {}
    issues = []
    t_start = time.time()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    log(f"Loading config from: {ENV_PATH}")
    config = Config.load(ENV_PATH)

    log("Creating MCP services...")
    services = await create_mcp_services(config, PROJECT_ID)
    log("Services created.")

    # ── Step 1: Create Session ─────────────────────────────────────────
    log("Step 1: Create session")
    try:
        r = await create_session(
            services,
            project_id=PROJECT_ID,
            description="Feature implementation test - TEST_03 - Add ai stats CLI command",
        )
        session_id = r.get("session_id")
        if not session_id:
            raise RuntimeError(f"Session creation failed: {r}")
        log(f"Session created: {session_id}")
        results["setup_session"] = {"pass": True, "session_id": session_id}
    except Exception as e:
        results["setup_session"] = {"pass": False, "error": str(e)}
        issues.append({"severity": "CRITICAL", "test": "setup_session", "msg": str(e)})
        _write_results(results, issues, t_start)
        return

    # ── Step 2: Index Codebase ─────────────────────────────────────────
    log("Step 2: Index codebase (wait_for_completion=True, wait_timeout=1800)")
    t_idx = time.time()
    try:
        idx_r = await add_knowledge(
            services=services,
            session_id=session_id,
            content_type="directory",
            source=CODEBASE_PATH,
            wait_for_completion=True,
            wait_timeout=1800,
        )
        idx_elapsed = time.time() - t_idx
        log(
            f"Indexing result: status={idx_r.get('status')}, elapsed={idx_elapsed:.1f}s"
        )
        log(
            f"  files={idx_r.get('files_processed', idx_r.get('items_processed', '?'))}, "
            f"chunks={idx_r.get('chunks_created', '?')}, "
            f"rels={idx_r.get('relationships_created', '?')}"
        )
        idx_ok = (
            idx_r.get("status") in ("completed", "done")
            or idx_r.get("completed") is True
        )
        results["setup_index"] = {
            "pass": idx_ok,
            "elapsed_s": round(idx_elapsed, 1),
            "files": idx_r.get("files_processed", idx_r.get("items_processed", 0)),
            "chunks": idx_r.get("chunks_created", 0),
            "rels": idx_r.get("relationships_created", 0),
            "status": idx_r.get("status"),
        }
        if not idx_ok:
            issues.append(
                {
                    "severity": "HIGH",
                    "test": "setup_index",
                    "msg": f"Indexing incomplete: {idx_r.get('status')}",
                }
            )
    except Exception as e:
        log(f"Indexing error: {e}")
        results["setup_index"] = {"pass": False, "error": str(e)}
        issues.append({"severity": "HIGH", "test": "setup_index", "msg": str(e)})

    # ── Step 3: Verify Index Health ────────────────────────────────────
    log("Step 3: Verify index health")
    try:
        info_r = await get_project_info(services=services, session_id=session_id)
        log(f"  Project info: {json.dumps(info_r, default=str)[:500]}")
        results["setup_verify"] = {"pass": True, "info": info_r}
    except Exception as e:
        log(f"  get_project_info error: {e}")
        results["setup_verify"] = {"pass": False, "error": str(e)}
        issues.append({"severity": "MEDIUM", "test": "setup_verify", "msg": str(e)})

    # ══════════════════════════════════════════════════════════════════
    # TEST 1: Find Related Code
    # Feature: Add `ai stats` CLI command (similar to existing commands)
    # ══════════════════════════════════════════════════════════════════
    log("=" * 60)
    log("TEST 1: Find Related Code")

    # T1.1a: Search for existing CLI commands
    log("T1.1a: Search for existing CLI command implementations")
    t1_start = time.time()
    try:
        r_cli = await search_knowledge(
            services=services,
            session_id=session_id,
            query="CLI command implementation entry point",
            limit=10,
        )
        results_count = len(r_cli.get("results", []))
        log(
            f"  Query 'CLI command implementation entry point': {results_count} results"
        )
        for item in r_cli.get("results", [])[:5]:
            log(
                f"    - {item.get('file_path', item.get('path', '?'))} [{item.get('score', 0):.3f}]"
            )
        results["t1_1a_cli_search"] = {
            "pass": results_count > 0,
            "count": results_count,
            "query": "CLI command implementation entry point",
        }
    except Exception as e:
        log(f"  Error: {e}")
        results["t1_1a_cli_search"] = {"pass": False, "error": str(e)}
        issues.append({"severity": "HIGH", "test": "t1_1a_cli_search", "msg": str(e)})

    # T1.1b: Search for ai index search commands
    log("T1.1b: Search for ai index, search command handlers")
    try:
        r_cmds = await search_knowledge(
            services=services,
            session_id=session_id,
            query="ai index search command handler argparse click typer",
            limit=10,
        )
        results_count = len(r_cmds.get("results", []))
        log(f"  Query 'ai command handler': {results_count} results")
        for item in r_cmds.get("results", [])[:5]:
            log(
                f"    - {item.get('file_path', item.get('path', '?'))} [{item.get('score', 0):.3f}]"
            )
        results["t1_1b_cmd_search"] = {
            "pass": results_count > 0,
            "count": results_count,
        }
    except Exception as e:
        log(f"  Error: {e}")
        results["t1_1b_cmd_search"] = {"pass": False, "error": str(e)}
        issues.append({"severity": "HIGH", "test": "t1_1b_cmd_search", "msg": str(e)})

    # T1.1c: Search for CLI module structure
    log("T1.1c: Search for CLI module structure")
    try:
        r_cli2 = await search_knowledge(
            services=services,
            session_id=session_id,
            query="agentic-inquiry CLI module commands main",
            limit=10,
        )
        results_count = len(r_cli2.get("results", []))
        log(f"  Query 'agentic-inquiry CLI module': {results_count} results")
        for item in r_cli2.get("results", [])[:5]:
            log(
                f"    - {item.get('file_path', item.get('path', '?'))} [{item.get('score', 0):.3f}]"
            )
        results["t1_1c_module_search"] = {
            "pass": results_count > 0,
            "count": results_count,
        }
        t1_1_elapsed = time.time() - t1_start
        results["t1_1_elapsed"] = round(t1_1_elapsed, 1)
        log(f"  T1.1 total elapsed: {t1_1_elapsed:.1f}s")
    except Exception as e:
        log(f"  Error: {e}")
        results["t1_1c_module_search"] = {"pass": False, "error": str(e)}
        issues.append(
            {"severity": "HIGH", "test": "t1_1c_module_search", "msg": str(e)}
        )

    # T1.2: Pattern recognition - search for existing command patterns
    log(
        "T1.2: Pattern recognition - search for command registration and dispatch patterns"
    )
    try:
        r_pat = await search_knowledge(
            services=services,
            session_id=session_id,
            query="command registration subcommand add_parser subparsers dispatch",
            limit=10,
        )
        results_count = len(r_pat.get("results", []))
        log(f"  Pattern search: {results_count} results")
        for item in r_pat.get("results", [])[:5]:
            log(
                f"    - {item.get('file_path', item.get('path', '?'))} [{item.get('score', 0):.3f}]"
            )
        results["t1_2_pattern"] = {
            "pass": results_count > 0,
            "count": results_count,
        }
    except Exception as e:
        log(f"  Error: {e}")
        results["t1_2_pattern"] = {"pass": False, "error": str(e)}
        issues.append({"severity": "MEDIUM", "test": "t1_2_pattern", "msg": str(e)})

    # T1.3: Code conventions - search for error handling / logging patterns
    log("T1.3: Code convention discovery")
    try:
        r_conv = await search_knowledge(
            services=services,
            session_id=session_id,
            query="logger info error handling async def return type hints convention",
            limit=10,
        )
        results_count = len(r_conv.get("results", []))
        log(f"  Convention search: {results_count} results")
        results["t1_3_conventions"] = {
            "pass": results_count > 0,
            "count": results_count,
        }
    except Exception as e:
        log(f"  Error: {e}")
        results["t1_3_conventions"] = {"pass": False, "error": str(e)}
        issues.append({"severity": "LOW", "test": "t1_3_conventions", "msg": str(e)})

    # ══════════════════════════════════════════════════════════════════
    # TEST 2: Identify Insertion Points
    # ══════════════════════════════════════════════════════════════════
    log("=" * 60)
    log("TEST 2: Identify Insertion Points")

    # T2.1: Primary implementation location
    log("T2.1: Find where to add stats command implementation")
    try:
        r_insert = await search_knowledge(
            services=services,
            session_id=session_id,
            query="CLI commands directory agentic-inquiry cli commands module files",
            limit=10,
        )
        results_count = len(r_insert.get("results", []))
        log(f"  Insertion point search: {results_count} results")
        for item in r_insert.get("results", [])[:5]:
            log(
                f"    - {item.get('file_path', item.get('path', '?'))} [{item.get('score', 0):.3f}]"
            )
        results["t2_1_insertion"] = {
            "pass": results_count > 0,
            "count": results_count,
        }
    except Exception as e:
        log(f"  Error: {e}")
        results["t2_1_insertion"] = {"pass": False, "error": str(e)}
        issues.append({"severity": "HIGH", "test": "t2_1_insertion", "msg": str(e)})

    # T2.2: Integration points
    log("T2.2: Find integration points - where commands are wired up")
    try:
        r_integ = await search_knowledge(
            services=services,
            session_id=session_id,
            query="main entry point CLI commands registered wired setup",
            limit=10,
        )
        results_count = len(r_integ.get("results", []))
        log(f"  Integration points: {results_count} results")
        for item in r_integ.get("results", [])[:5]:
            log(
                f"    - {item.get('file_path', item.get('path', '?'))} [{item.get('score', 0):.3f}]"
            )
        results["t2_2_integration"] = {
            "pass": results_count > 0,
            "count": results_count,
        }
    except Exception as e:
        log(f"  Error: {e}")
        results["t2_2_integration"] = {"pass": False, "error": str(e)}
        issues.append({"severity": "HIGH", "test": "t2_2_integration", "msg": str(e)})

    # T2.3: Test location
    log("T2.3: Find test patterns for CLI commands")
    try:
        r_test_loc = await search_knowledge(
            services=services,
            session_id=session_id,
            query="test CLI command pytest fixture mock test_cli",
            limit=10,
        )
        results_count = len(r_test_loc.get("results", []))
        log(f"  Test location search: {results_count} results")
        for item in r_test_loc.get("results", [])[:5]:
            log(
                f"    - {item.get('file_path', item.get('path', '?'))} [{item.get('score', 0):.3f}]"
            )
        results["t2_3_test_location"] = {
            "pass": results_count > 0,
            "count": results_count,
        }
    except Exception as e:
        log(f"  Error: {e}")
        results["t2_3_test_location"] = {"pass": False, "error": str(e)}
        issues.append(
            {"severity": "MEDIUM", "test": "t2_3_test_location", "msg": str(e)}
        )

    # ══════════════════════════════════════════════════════════════════
    # TEST 3: Dependency Analysis
    # ══════════════════════════════════════════════════════════════════
    log("=" * 60)
    log("TEST 3: Dependency Analysis")

    # T3.1: Direct dependencies
    log("T3.1: Find dependencies - StorageFacade, Config usage in CLI")
    try:
        r_deps = await search_knowledge(
            services=services,
            session_id=session_id,
            query="StorageFacade Config import CLI commands dependency injection",
            limit=10,
        )
        results_count = len(r_deps.get("results", []))
        log(f"  Dependency search: {results_count} results")
        results["t3_1_dependencies"] = {
            "pass": results_count > 0,
            "count": results_count,
        }
    except Exception as e:
        log(f"  Error: {e}")
        results["t3_1_dependencies"] = {"pass": False, "error": str(e)}
        issues.append(
            {"severity": "MEDIUM", "test": "t3_1_dependencies", "msg": str(e)}
        )

    # T3.2: Impact assessment - what would be affected
    log("T3.2: Impact assessment via analyze_impact")
    try:
        r_impact = await analyze_impact(
            services=services,
            session_id=session_id,
            entity="cli",
        )
        log(f"  Impact result: {json.dumps(r_impact, default=str)[:400]}")
        has_data = bool(
            r_impact.get("affected_components")
            or r_impact.get("impact_score")
            or r_impact.get("results")
        )
        results["t3_2_impact"] = {
            "pass": True,  # tool ran without error
            "has_data": has_data,
            "impact": r_impact,
        }
    except Exception as e:
        log(f"  analyze_impact error: {e}")
        # Non-critical - use search as fallback
        try:
            r_impact_fb = await search_knowledge(
                services=services,
                session_id=session_id,
                query="what breaks if CLI module changes backward compatibility",
                limit=10,
            )
            results["t3_2_impact"] = {
                "pass": True,
                "fallback": True,
                "count": len(r_impact_fb.get("results", [])),
            }
        except Exception as e2:
            results["t3_2_impact"] = {"pass": False, "error": str(e2)}
            issues.append({"severity": "LOW", "test": "t3_2_impact", "msg": str(e2)})

    # ══════════════════════════════════════════════════════════════════
    # TEST 4: Implementation Planning
    # ══════════════════════════════════════════════════════════════════
    log("=" * 60)
    log("TEST 4: Implementation Planning - search for patterns to replicate")

    # T4.1: Find existing similar commands for step-by-step plan
    log("T4.1: Search for index command implementation as model to follow")
    try:
        r_model = await search_knowledge(
            services=services,
            session_id=session_id,
            query="index command implementation function async run_index",
            limit=10,
        )
        results_count = len(r_model.get("results", []))
        log(f"  Model command search: {results_count} results")
        for item in r_model.get("results", [])[:5]:
            log(
                f"    - {item.get('file_path', item.get('path', '?'))} [{item.get('score', 0):.3f}]"
            )
        results["t4_1_step_plan"] = {
            "pass": results_count > 0,
            "count": results_count,
        }
    except Exception as e:
        log(f"  Error: {e}")
        results["t4_1_step_plan"] = {"pass": False, "error": str(e)}
        issues.append({"severity": "MEDIUM", "test": "t4_1_step_plan", "msg": str(e)})

    # T4.2: Search for configuration patterns to understand checklist
    log("T4.2: Code checklist search - find pyproject.toml scripts registration")
    try:
        r_checklist = await search_knowledge(
            services=services,
            session_id=session_id,
            query="pyproject.toml scripts entry_points console_scripts ai",
            limit=10,
        )
        results_count = len(r_checklist.get("results", []))
        log(f"  Checklist search: {results_count} results")
        results["t4_2_checklist"] = {
            "pass": results_count > 0,
            "count": results_count,
        }
    except Exception as e:
        log(f"  Error: {e}")
        results["t4_2_checklist"] = {"pass": False, "error": str(e)}
        issues.append({"severity": "LOW", "test": "t4_2_checklist", "msg": str(e)})

    # ══════════════════════════════════════════════════════════════════
    # TEST 5: Knowledge Capture
    # ══════════════════════════════════════════════════════════════════
    log("=" * 60)
    log("TEST 5: Knowledge Capture")

    # T5.1: Store implementation plan
    log("T5.1: Store implementation plan memories")
    memories_stored = []
    try:
        m1 = await save_memory(
            services=services,
            session_id=session_id,
            summary="Add ai stats CLI command - implementation approach",
            content="Implementation approach: Add 'ai stats' CLI command following the pattern of existing CLI commands (index, search). Create stats.py in agentic_inquiry/cli/commands/, implement async run_stats() function, register in main CLI dispatcher.",
            importance=0.9,
            tags=["feature", "cli", "stats", "implementation"],
        )
        log(f"  Memory 1 stored: {m1.get('memory_id', m1.get('id', 'unknown'))}")
        memories_stored.append("implementation_approach")

        m2 = await save_memory(
            services=services,
            session_id=session_id,
            summary="CLI command pattern - async handlers with Config/StorageFacade",
            content="Pattern to follow: Existing CLI commands use async functions with Config and StorageFacade injection. Commands are registered via add_subparsers() or similar dispatch table. Follow naming convention: run_<command> as the async handler.",
            importance=0.85,
            tags=["feature", "cli", "pattern", "convention"],
        )
        log(f"  Memory 2 stored: {m2.get('memory_id', m2.get('id', 'unknown'))}")
        memories_stored.append("pattern")

        m3 = await save_memory(
            services=services,
            session_id=session_id,
            summary="Stats command integration points - files to create/modify",
            content="Integration points: (1) agentic_inquiry/cli/__init__.py or main.py - register stats subcommand; (2) agentic_inquiry/cli/commands/ - add stats.py file; (3) pyproject.toml - if new script entry point needed; (4) tests/cli/ - add test_stats.py.",
            importance=0.88,
            tags=["feature", "cli", "integration-points", "stats"],
        )
        log(f"  Memory 3 stored: {m3.get('memory_id', m3.get('id', 'unknown'))}")
        memories_stored.append("integration_points")

        m4 = await save_memory(
            services=services,
            session_id=session_id,
            summary="Stats command risks - LOW risk, no breaking changes",
            content="Risks and mitigation: LOW risk - adding a new read-only stats command does not modify existing commands. Mitigation: ensure stats command handles empty index gracefully (zero chunks), add test for empty state. No breaking changes to existing interface.",
            importance=0.75,
            tags=["feature", "risk", "mitigation", "stats"],
        )
        log(f"  Memory 4 stored: {m4.get('memory_id', m4.get('id', 'unknown'))}")
        memories_stored.append("risks")

        results["t5_1_store"] = {
            "pass": True,
            "memories_stored": len(memories_stored),
            "memories": memories_stored,
        }
    except Exception as e:
        log(f"  Store memory error: {e}")
        results["t5_1_store"] = {
            "pass": len(memories_stored) > 0,
            "memories_stored": len(memories_stored),
            "error": str(e),
        }
        if len(memories_stored) == 0:
            issues.append({"severity": "MEDIUM", "test": "t5_1_store", "msg": str(e)})

    # T5.2: Verify retrievability
    log("T5.2: Verify memory retrievability")
    try:
        r_recall1 = await recall_memories(
            services=services,
            session_id=session_id,
            query="stats command feature implementation",
            limit=5,
        )
        recall_count1 = len(r_recall1.get("memories", r_recall1.get("results", [])))
        log(f"  Recall 'stats command feature': {recall_count1} memories")

        r_recall2 = await recall_memories(
            services=services,
            session_id=session_id,
            query="CLI pattern integration points",
            limit=5,
        )
        recall_count2 = len(r_recall2.get("memories", r_recall2.get("results", [])))
        log(f"  Recall 'CLI pattern integration points': {recall_count2} memories")

        results["t5_2_recall"] = {
            "pass": recall_count1 > 0 or recall_count2 > 0,
            "recall1_count": recall_count1,
            "recall2_count": recall_count2,
        }
    except Exception as e:
        log(f"  Recall error: {e}")
        results["t5_2_recall"] = {"pass": False, "error": str(e)}
        issues.append({"severity": "MEDIUM", "test": "t5_2_recall", "msg": str(e)})

    # ── Final Summary ──────────────────────────────────────────────────
    total_elapsed = time.time() - t_start
    log(f"All tests complete. Elapsed: {total_elapsed:.1f}s")

    _write_results(results, issues, t_start)


def _write_results(results: dict, issues: list, t_start: float):
    total_elapsed = time.time() - t_start
    total = len([k for k, v in results.items() if isinstance(v, dict) and "pass" in v])
    passed = len(
        [k for k, v in results.items() if isinstance(v, dict) and v.get("pass") is True]
    )

    summary = {
        "test_id": "TEST_03",
        "slug": "feature_implementation",
        "run_id": RUN_ID,
        "project_id": PROJECT_ID,
        "elapsed_s": round(total_elapsed, 1),
        "passed": passed,
        "total": total,
        "issues": issues,
        "results": results,
    }

    out_path = OUTPUT_DIR / "results.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n[DONE] Results written to: {out_path}")
    print(f"[DONE] Pass: {passed}/{total}, Issues: {len(issues)}")


if __name__ == "__main__":
    asyncio.run(main())
