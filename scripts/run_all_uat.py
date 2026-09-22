"""
Multi-test UAT runner that shares a single MCPServer across all tests.

Each test gets its own project_id for data isolation but shares connection pools.
This avoids the connection exhaustion problem when running tests in parallel.

Modes:
  --mode smoke   Quick 5-check smoke per test (default, fast)
  --mode full    Full protocol where available, smoke fallback otherwise

Usage:
    uv run python scripts/run_all_uat.py [--tests 01,06,12] [--mode full] [--config PATH]
"""
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Also add tests dir so protocols can be imported
sys.path.insert(0, str(PROJECT_ROOT / "tests/01-agents"))

DEFAULT_CONFIG = str(PROJECT_ROOT / ".agentic-inquiry/envs/ai-prod/config.yaml")
TEST_DIR = PROJECT_ROOT / "tests/01-agents"

# Test registry — maps test ID to slug and protocol file
TESTS = {
    "01": ("core", "TEST_01_CORE_FUNCTIONALITY.md"),
    "02": ("onboarding", "TEST_02_ONBOARDING.md"),
    "03": ("feature_implementation", "TEST_03_FEATURE_IMPLEMENTATION.md"),
    "04": ("bug_investigation", "TEST_04_BUG_INVESTIGATION.md"),
    "05": ("major_refactoring", "TEST_05_MAJOR_REFACTORING.md"),
    "06": ("knowledge_building", "TEST_06_KNOWLEDGE_BUILDING.md"),
    "07": ("code_review", "TEST_07_CODE_REVIEW.md"),
    "08": ("documentation", "TEST_08_DOCUMENTATION_GENERATION.md"),
    "09": ("dependency_analysis", "TEST_09_DEPENDENCY_ANALYSIS.md"),
    "10": ("performance", "TEST_10_PERFORMANCE_INVESTIGATION.md"),
    "11": ("api_design", "TEST_11_API_DESIGN.md"),
    "12": ("code_graph", "TEST_12_CODE_GRAPH.md"),
    "13": ("document_graph", "TEST_13_DOCUMENT_GRAPH.md"),
    "14": ("semantic_graph", "TEST_14_SEMANTIC_GRAPH.md"),
}


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


async def create_shared_server(config_path: str):
    """Create a single MCPServer instance shared across all tests."""
    from agentic_inquiry.config import Config
    from agentic_inquiry.mcp.server import MCPServer

    log(f"Loading config: {config_path}")
    config = Config.load_with_overlay(config_path)
    log(f"Backend: {config.storage.backend}")

    server = MCPServer(config=config, project_id="shared_uat_server")
    log("Initializing shared MCPServer...")
    t0 = time.time()
    await server.initialize()
    log(f"MCPServer ready in {time.time() - t0:.1f}s")

    return server


async def run_test(
    services: dict,
    test_id: str,
    slug: str,
    run_id: str,
    output_dir: Path,
    mode: str = "smoke",
) -> Dict[str, Any]:
    """Run a single test using the shared services dict."""
    from protocols import get_protocol

    log(f"\n{'='*60}")
    protocol_fn = get_protocol(test_id, mode)
    protocol_name = protocol_fn.__module__.split(".")[-1]
    log(f"TEST_{test_id}: {slug} (protocol: {protocol_name}, mode: {mode})")
    log(f"{'='*60}")

    try:
        result = await protocol_fn(
            services=services,
            test_id=test_id,
            slug=slug,
            run_id=run_id,
            output_dir=output_dir,
        )
        return result
    except Exception as e:
        log(f"  EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return {
            "test_id": test_id,
            "slug": slug,
            "status": "error",
            "error": str(e),
            "elapsed": 0,
        }


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run ai UAT tests with shared server")
    parser.add_argument("--tests", default="ALL", help="Comma-separated test IDs or ALL")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Config overlay path")
    parser.add_argument("--parallel", type=int, default=3, help="Max parallel tests")
    parser.add_argument(
        "--mode",
        choices=["smoke", "full"],
        default="smoke",
        help="smoke = quick 5-check per test; full = full protocol where available",
    )
    args = parser.parse_args()

    # Select tests
    if args.tests.upper() == "ALL":
        test_ids = sorted(TESTS.keys())
    else:
        test_ids = [t.strip().zfill(2) for t in args.tests.split(",")]
        # Validate
        invalid = [t for t in test_ids if t not in TESTS]
        if invalid:
            print(f"Unknown test IDs: {invalid}. Valid: {sorted(TESTS.keys())}")
            sys.exit(1)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = PROJECT_ROOT / "test_results" / "ai" / run_id

    log(f"UAT Run: {run_id}")
    log(f"Mode: {args.mode}")
    log(f"Tests: {', '.join(test_ids)}")
    log(f"Parallel: {args.parallel}")
    log(f"Output: {base_dir}")

    # Show which tests have full protocols
    if args.mode == "full":
        from protocols import FULL_PROTOCOLS
        full_ids = set(FULL_PROTOCOLS.keys()) & set(test_ids)
        smoke_ids = set(test_ids) - full_ids
        if full_ids:
            log(f"Full protocol: {', '.join(sorted(full_ids))}")
        if smoke_ids:
            log(f"Smoke fallback: {', '.join(sorted(smoke_ids))}")

    # Create shared server
    server = await create_shared_server(args.config)
    services = server.services

    # Run tests with concurrency limit
    semaphore = asyncio.Semaphore(args.parallel)
    all_results: Dict[str, Any] = {}

    async def run_with_limit(test_id: str):
        async with semaphore:
            slug, _ = TESTS[test_id]
            output_dir = base_dir / slug
            return await run_test(services, test_id, slug, run_id, output_dir, args.mode)

    # Run all tests concurrently (semaphore limits parallelism)
    tasks = [run_with_limit(tid) for tid in test_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for tid, result in zip(test_ids, results):
        if isinstance(result, Exception):
            all_results[tid] = {"status": "error", "error": str(result)}
        else:
            all_results[tid] = result

    # ── Summary ─────────────────────────────────────────────────
    log(f"\n{'='*60}")
    log(f"RESULTS SUMMARY ({args.mode} mode)")
    log(f"{'='*60}")

    total_checks = 0
    total_passed_checks = 0

    for tid in test_ids:
        r = all_results[tid]
        status = r.get("status", "error")
        rate = r.get("pass_rate", "?/?")
        elapsed = r.get("elapsed", 0)
        slug = TESTS[tid][0]
        passed_count = r.get("passed", 0)
        total_count = r.get("total", 0)
        total_checks += total_count
        total_passed_checks += passed_count

        # Color-code status
        adoption = r.get("adoption_score", "-")
        method = r.get("adoption_method", "?")
        icon = "+" if status == "pass" else "~" if status == "partial" else "-"
        log(f"  [{icon}] TEST_{tid} {slug}: {status} ({rate}) adoption={adoption}/10 [{method}] [{elapsed}s]")

    log(f"\nOverall: {total_passed_checks}/{total_checks} checks passed across {len(test_ids)} tests")

    passed_tests = sum(1 for r in all_results.values() if r.get("status") == "pass")
    adoption_scores = [r.get("adoption_score", 0) for r in all_results.values() if r.get("adoption_score")]
    avg_adoption = round(sum(adoption_scores) / len(adoption_scores), 1) if adoption_scores else 0
    log(f"Tests: {passed_tests}/{len(all_results)} fully passed")
    log(f"Adoption: avg={avg_adoption}/10 (min={min(adoption_scores) if adoption_scores else 0}, max={max(adoption_scores) if adoption_scores else 0})")
    log(f"Adoption method: heuristic (agent scoring available via adoption_evidence in results.json)")

    # Write summary
    summary_path = base_dir / "SUMMARY.json"
    base_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "run_id": run_id,
        "mode": args.mode,
        "tests_run": len(test_ids),
        "tests_passed": passed_tests,
        "total_checks": total_checks,
        "checks_passed": total_passed_checks,
        "results": all_results,
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    log(f"Summary: {summary_path}")

    await server.shutdown()
    log("Done.")

    # Exit with non-zero if any test failed
    if passed_tests < len(all_results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
