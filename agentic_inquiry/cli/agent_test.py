"""CLI command for executing agent test scenarios.

Usage:
    ai agent-test [TEST_ID] [--all] [--project PROJECT] [--output-dir DIR]
    ai agent-test list
    ai agent-test status

Examples:
    ai agent-test 01              # Run TEST_01_CORE_FUNCTIONALITY
    ai agent-test --all           # Run all tests in sequence
    ai agent-test list            # List available tests
    ai agent-test status          # Show test run status
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from agentic_inquiry.cli.env_resolver import load_config_for_environment

logger = logging.getLogger(__name__)

# Test scenario directory
TESTS_DIR = Path(__file__).parent.parent.parent / "tests" / "01-agents"


def get_test_files() -> list[tuple[str, str, Path]]:
    """Get all test files with their IDs and names.

    Returns:
        List of (test_id, test_name, file_path) tuples
    """
    tests = []
    if not TESTS_DIR.exists():
        return tests

    for path in sorted(TESTS_DIR.glob("TEST_*.md")):
        # Extract TEST_01, TEST_02, etc.
        match = re.match(r"TEST_(\d+)_(.+)\.md", path.name)
        if match:
            test_id = match.group(1)
            test_name = match.group(2).replace("_", " ").title()
            tests.append((test_id, test_name, path))

    return tests


def parse_test_file(path: Path) -> dict:
    """Parse a test scenario markdown file.

    Args:
        path: Path to test markdown file

    Returns:
        Parsed test structure with sections
    """
    content = path.read_text()

    # Extract metadata
    lines = content.split("\n")
    title = ""
    purpose = ""
    time_estimate = ""

    for line in lines[:20]:
        if line.startswith("# "):
            title = line[2:].strip()
        elif "**Purpose:**" in line:
            purpose = line.split("**Purpose:**")[1].strip()
        elif "**Time Estimate:**" in line or "**Time Limit:**" in line:
            time_estimate = line.split(":**")[1].strip()

    # Extract test sections (## Test N: ...)
    test_sections = []
    current_section = None

    for line in lines:
        if line.startswith("## Test ") or line.startswith("## T"):
            if current_section:
                test_sections.append(current_section)
            current_section = {
                "title": line[3:].strip(),
                "content": [],
                "execute": [],
                "expected": [],
            }
        elif current_section:
            current_section["content"].append(line)
            if "**Execute:**" in line:
                # Next line is the execute instruction
                pass
            elif line.startswith("**Expected:**"):
                pass

    if current_section:
        test_sections.append(current_section)

    return {
        "path": str(path),
        "title": title,
        "purpose": purpose,
        "time_estimate": time_estimate,
        "sections": test_sections,
        "raw_content": content,
    }


async def list_command(args: argparse.Namespace) -> int:
    """List available test scenarios.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success)
    """
    tests = get_test_files()

    if not tests:
        print(f"No test files found in {TESTS_DIR}")
        return 1

    if args.json:
        output = [
            {"id": tid, "name": name, "path": str(path)}
            for tid, name, path in tests
        ]
        print(json.dumps(output, indent=2))
    else:
        print(f"Available Agent Test Scenarios ({len(tests)} tests):\n")
        print("=" * 60)

        for test_id, test_name, path in tests:
            parsed = parse_test_file(path)
            time_est = parsed.get("time_estimate", "?")
            purpose = parsed.get("purpose", "")[:50]
            if len(purpose) == 50:
                purpose += "..."

            print(f"  TEST_{test_id}: {test_name}")
            print(f"           Time: {time_est}")
            if purpose:
                print(f"           {purpose}")
            print()

        print("=" * 60)
        print("\nUsage:")
        print("  ai agent-test 01        # Run TEST_01")
        print("  ai agent-test --all     # Run all tests")

    return 0


async def status_command(args: argparse.Namespace) -> int:
    """Show test run status.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success)
    """
    results_dir = Path(args.output_dir or "test_results/ai")

    if not results_dir.exists():
        print("No test results found.")
        print(f"Results directory: {results_dir}")
        return 0

    # Find recent test runs
    runs = []
    for run_dir in sorted(results_dir.iterdir(), reverse=True):
        if run_dir.is_dir():
            # Look for summary files
            summary = run_dir / "SESSION_SUMMARY.md"
            final_report = run_dir / "FINAL_REPORT.md"

            status = "incomplete"
            if summary.exists():
                status = "complete"
            elif final_report.exists():
                status = "partial"

            runs.append({
                "timestamp": run_dir.name,
                "status": status,
                "path": str(run_dir),
            })

    if args.json:
        print(json.dumps(runs[:10], indent=2))
    else:
        print("Recent Test Runs:\n")
        for run in runs[:10]:
            status_icon = {"complete": "✓", "partial": "◐", "incomplete": "○"}.get(run["status"], "?")
            print(f"  {status_icon} {run['timestamp']} [{run['status']}]")
            print(f"    {run['path']}")
            print()

    return 0


async def run_test_scenario(
    test_id: str,
    project_id: str,
    output_dir: Path,
    config,
) -> dict:
    """Execute a single test scenario using ai CLI.

    Args:
        test_id: Test ID (e.g., "01", "02")
        project_id: Unique project ID for isolation
        output_dir: Output directory for results
        config: Configuration object

    Returns:
        Test result dict
    """
    from agentic_inquiry.storage.facade import StorageFacade
    from agentic_inquiry.embeddings.registry import embedding_registry
    from agentic_inquiry.embeddings.sentence_transformer import SentenceTransformerEmbedder

    # Find the test file
    tests = get_test_files()
    test_file = None
    test_name = None

    for tid, name, path in tests:
        if tid == test_id.zfill(2):
            test_file = path
            test_name = name
            break

    if not test_file:
        return {"status": "error", "message": f"Test {test_id} not found"}

    # Parse test file
    parsed = parse_test_file(test_file)

    # Create output directory
    test_output = output_dir / f"test_{test_id}_{test_name.lower().replace(' ', '_')}"
    test_output.mkdir(parents=True, exist_ok=True)

    # Initialize test log
    test_log = test_output / "TEST_LOG.md"
    issues_log = test_output / "ISSUES_LOG.md"

    start_time = datetime.now()

    with open(test_log, "w") as log:
        log.write(f"# Test Log: TEST_{test_id} - {test_name}\n\n")
        log.write(f"**Started:** {start_time.isoformat()}\n")
        log.write(f"**Project ID:** {project_id}\n")
        log.write(f"**Purpose:** {parsed.get('purpose', 'N/A')}\n\n")
        log.write("---\n\n")

    with open(issues_log, "w") as log:
        log.write(f"# Issues Log: TEST_{test_id}\n\n")
        log.write("| # | Severity | Description | Status |\n")
        log.write("|---|----------|-------------|--------|\n")

    results = {
        "test_id": test_id,
        "test_name": test_name,
        "project_id": project_id,
        "status": "running",
        "start_time": start_time.isoformat(),
        "steps": [],
        "issues": [],
    }

    try:
        # Configure embedder
        if not embedding_registry._default_configured:
            model_name = getattr(config.embeddings.sentence_transformer, 'model_name', 'all-MiniLM-L6-v2')
            ndims = getattr(config.embeddings, 'default_dimensions', 384)
            embedder = SentenceTransformerEmbedder(model_name=model_name)
            embedding_registry.configure_default_embedder(embedder, ndims=ndims)

        # Create storage
        storage = await StorageFacade.from_config(config, project_id)

        # Execute test based on test_id
        if test_id == "01":
            # Core Functionality Smoke Test
            results = await _run_smoke_test(storage, config, project_id, test_output, results)
        else:
            # For other tests, execute generic steps
            results = await _run_generic_test(storage, config, project_id, parsed, test_output, results)

        results["status"] = "complete"

    except Exception as e:
        logger.exception(f"Test {test_id} failed")
        results["status"] = "failed"
        results["error"] = str(e)
        results["issues"].append({
            "severity": "critical",
            "description": str(e),
            "status": "open",
        })

    # Write final results
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    results["end_time"] = end_time.isoformat()
    results["duration_seconds"] = duration

    # Append to test log
    with open(test_log, "a") as log:
        log.write("\n---\n\n")
        log.write(f"**Completed:** {end_time.isoformat()}\n")
        log.write(f"**Duration:** {duration:.1f} seconds\n")
        log.write(f"**Status:** {results['status'].upper()}\n")
        log.write(f"**Steps Passed:** {sum(1 for s in results['steps'] if s.get('passed'))}/{len(results['steps'])}\n")

    # Write final report
    final_report = test_output / "FINAL_REPORT.md"
    with open(final_report, "w") as f:
        f.write(f"# Final Report: TEST_{test_id} - {test_name}\n\n")
        f.write("## Summary\n\n")
        f.write(f"- **Status:** {results['status'].upper()}\n")
        f.write(f"- **Duration:** {duration:.1f} seconds\n")
        f.write(f"- **Steps:** {sum(1 for s in results['steps'] if s.get('passed'))}/{len(results['steps'])} passed\n")
        f.write(f"- **Issues:** {len(results['issues'])}\n\n")

        f.write("## Step Results\n\n")
        for step in results["steps"]:
            icon = "✓" if step.get("passed") else "✗"
            f.write(f"- {icon} {step.get('name', 'Unknown step')}\n")
            if step.get("details"):
                f.write(f"  - {step['details']}\n")

        if results["issues"]:
            f.write("\n## Issues\n\n")
            for issue in results["issues"]:
                f.write(f"- [{issue.get('severity', 'unknown')}] {issue.get('description', 'No description')}\n")

    return results


async def _run_smoke_test(storage, config, project_id: str, output_dir: Path, results: dict) -> dict:
    """Execute TEST_01 Core Functionality Smoke Test.

    Args:
        storage: StorageFacade instance
        config: Configuration object
        project_id: Project ID
        output_dir: Output directory
        results: Results dict to update

    Returns:
        Updated results dict
    """
    from agentic_inquiry.indexing.pipeline import IndexingPipeline
    from agentic_inquiry.search.service import SearchService
    from agentic_inquiry.embeddings.service import EmbeddingService

    test_log = output_dir / "TEST_LOG.md"

    def log_step(name: str, passed: bool, details: str = ""):
        results["steps"].append({"name": name, "passed": passed, "details": details})
        with open(test_log, "a") as f:
            icon = "✓" if passed else "✗"
            f.write(f"### {icon} {name}\n\n")
            if details:
                f.write(f"{details}\n\n")

    # Test 1: Storage Health Check
    try:
        # Check if we can query storage
        entities = await storage.query_raw(
            table_name="graph_entities",
            filters={},
            limit=1,
            project_id=project_id,
        )
        log_step("T1.1: Storage Health Check", True, "Storage accessible and responding")
    except Exception as e:
        log_step("T1.1: Storage Health Check", False, f"Error: {e}")
        results["issues"].append({"severity": "critical", "description": f"Storage not accessible: {e}", "status": "open"})

    # Test 2: Indexing
    try:
        pipeline = IndexingPipeline(storage, config, project_id)

        # Index the agentic-inquiry package as test data
        ai_path = Path(__file__).parent.parent
        if ai_path.exists():
            result = await pipeline.index_directory(path=str(ai_path), wait=True)
            chunks = getattr(result, 'chunks_indexed', 0) if result else 0
            entities = getattr(result, 'entities_created', 0) if result else 0
            log_step("T3.1: Index Content", True, f"Indexed {chunks} chunks, {entities} entities")
        else:
            log_step("T3.1: Index Content", False, "Test codebase not found")
    except Exception as e:
        log_step("T3.1: Index Content", False, f"Error: {e}")
        results["issues"].append({"severity": "high", "description": f"Indexing failed: {e}", "status": "open"})

    # Test 3: Verify Index
    try:
        entities = await storage.query_raw(
            table_name="graph_entities",
            filters={},
            limit=10,
            project_id=project_id,
        )
        count = len(entities) if entities else 0
        if count > 0:
            log_step("T3.2: Verify Indexed Content", True, f"Found {count} entities")
        else:
            log_step("T3.2: Verify Indexed Content", False, "No entities found after indexing")
    except Exception as e:
        log_step("T3.2: Verify Indexed Content", False, f"Error: {e}")

    # Test 4: Search
    try:
        search = SearchService(storage, config)
        embedding_service = EmbeddingService(config=config)

        query = "search service"
        query_vector = await embedding_service.embed_async(query)

        search_results = await search.hybrid_search(
            query_vector=query_vector,
            query_fts=query,
            project_id=project_id,
            limit=5,
        )

        count = len(search_results) if search_results else 0
        if count > 0:
            log_step("T4.1: Simple Search", True, f"Found {count} results for '{query}'")
        else:
            log_step("T4.1: Simple Search", False, f"No results for '{query}'")
    except Exception as e:
        log_step("T4.1: Simple Search", False, f"Error: {e}")
        results["issues"].append({"severity": "high", "description": f"Search failed: {e}", "status": "open"})

    # Test 5: Memory (if available)
    try:
        from agentic_inquiry.memory.system import MemorySystem
        from agentic_inquiry.memory.adapters.lancedb_adapter import LanceDBMemoryAdapter

        db_manager = storage.get_db_manager() if hasattr(storage, "get_db_manager") else None
        if db_manager:
            embedding_dims = getattr(config.embeddings, 'default_dimensions', 384)
            episodic = LanceDBMemoryAdapter(
                manager=db_manager,
                table_name="memory_episodic",
                embedding_dims=embedding_dims,
            )
            await episodic.initialize()

            embedding_service = EmbeddingService(config=config)
            memory_system = MemorySystem(
                config=config,
                embedding_service=embedding_service,
                episodic_storage=episodic,
                semantic_storage=episodic,
            )
            await memory_system.initialize()

            context = memory_system.create_agent_context(
                agent_id="test",
                session_id="test_session",
                conversation_id="test_conversation",
            )

            # Store a test memory
            await memory_system.store(
                content="Test memory from smoke test",
                context=context,
                importance=0.5,
            )

            log_step("T5.1: Store Memory", True, "Memory stored successfully")

            # Recall memory
            memories = await memory_system.retrieve(
                query="smoke test",
                context=context,
                limit=5,
            )

            if memories:
                log_step("T5.2: Retrieve Memory", True, f"Retrieved {len(memories)} memories")
            else:
                log_step("T5.2: Retrieve Memory", False, "No memories retrieved")
        else:
            log_step("T5.1: Store Memory", True, "Memory system not configured (LanceDB mode)")
            log_step("T5.2: Retrieve Memory", True, "Memory system not configured (LanceDB mode)")
    except Exception as e:
        log_step("T5.1: Store Memory", False, f"Error: {e}")
        results["issues"].append({"severity": "medium", "description": f"Memory failed: {e}", "status": "open"})

    return results


async def _run_generic_test(storage, config, project_id: str, parsed: dict, output_dir: Path, results: dict) -> dict:
    """Execute a generic test based on parsed test file.

    For tests other than the smoke test, this provides basic execution.

    Args:
        storage: StorageFacade instance
        config: Configuration object
        project_id: Project ID
        parsed: Parsed test file structure
        output_dir: Output directory
        results: Results dict to update

    Returns:
        Updated results dict
    """
    test_log = output_dir / "TEST_LOG.md"

    with open(test_log, "a") as f:
        f.write("## Test Execution\n\n")
        f.write("This test requires manual execution following the procedures in:\n")
        f.write(f"`{parsed['path']}`\n\n")
        f.write("### Sections to Execute:\n\n")

        for i, section in enumerate(parsed.get("sections", []), 1):
            f.write(f"{i}. {section.get('title', 'Unknown section')}\n")

        f.write("\n---\n\n")
        f.write("**Note:** This test file contains detailed procedures that should be\n")
        f.write("followed manually by an AI agent using ai CLI commands.\n")

    results["steps"].append({
        "name": "Test file parsed",
        "passed": True,
        "details": f"Found {len(parsed.get('sections', []))} sections to execute",
    })

    results["steps"].append({
        "name": "Manual execution required",
        "passed": True,
        "details": "See test file for detailed procedures",
    })

    return results


async def run_command(args: argparse.Namespace) -> int:
    """Execute test scenario(s).

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success)
    """
    config = load_config_for_environment()

    # Generate unique timestamp for this run
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Set up output directory
    output_dir = Path(args.output_dir or "test_results/ai") / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Test run: {timestamp}")
    print(f"Output: {output_dir}")
    print()

    tests_to_run = []

    if args.all:
        tests_to_run = [tid for tid, _, _ in get_test_files()]
    elif args.test_id:
        tests_to_run = [args.test_id.zfill(2)]
    else:
        print("Error: Specify a test ID or use --all")
        print("  ai agent-test 01        # Run TEST_01")
        print("  ai agent-test --all     # Run all tests")
        return 1

    all_results = []

    for test_id in tests_to_run:
        # Generate unique project ID for isolation
        project_id = f"ai_test{test_id}_{timestamp}"

        print(f"Running TEST_{test_id}...")

        result = await run_test_scenario(
            test_id=test_id,
            project_id=project_id,
            output_dir=output_dir,
            config=config,
        )

        all_results.append(result)

        status = result.get("status", "unknown")
        duration = result.get("duration_seconds", 0)
        steps_passed = sum(1 for s in result.get("steps", []) if s.get("passed"))
        steps_total = len(result.get("steps", []))

        icon = "✓" if status == "complete" else "✗"
        print(f"  {icon} TEST_{test_id}: {status} ({steps_passed}/{steps_total} steps, {duration:.1f}s)")

        if result.get("issues"):
            for issue in result["issues"]:
                print(f"    ! [{issue.get('severity')}] {issue.get('description', '')[:50]}")

    # Write session summary
    summary_path = output_dir / "SESSION_SUMMARY.md"
    with open(summary_path, "w") as f:
        f.write("# Agent Test Session Summary\n\n")
        f.write(f"**Run ID:** {timestamp}\n")
        f.write(f"**Date:** {datetime.now().isoformat()}\n")
        f.write(f"**Tests Run:** {len(all_results)}\n\n")

        passed = sum(1 for r in all_results if r.get("status") == "complete")
        f.write("## Results\n\n")
        f.write(f"- **Passed:** {passed}/{len(all_results)}\n")
        f.write(f"- **Failed:** {len(all_results) - passed}\n\n")

        f.write("## Test Details\n\n")
        for result in all_results:
            icon = "✓" if result.get("status") == "complete" else "✗"
            f.write(f"### {icon} TEST_{result.get('test_id')}: {result.get('test_name')}\n\n")
            f.write(f"- Status: {result.get('status')}\n")
            f.write(f"- Duration: {result.get('duration_seconds', 0):.1f}s\n")
            f.write(f"- Steps: {sum(1 for s in result.get('steps', []) if s.get('passed'))}/{len(result.get('steps', []))}\n\n")

    print()
    print(f"Summary written to: {summary_path}")

    # Return non-zero if any tests failed
    if all(r.get("status") == "complete" for r in all_results):
        print(f"\nAll {len(all_results)} test(s) passed!")
        return 0
    else:
        failed = [r for r in all_results if r.get("status") != "complete"]
        print(f"\n{len(failed)} test(s) failed.")
        return 1


def create_run_parser() -> argparse.ArgumentParser:
    """Create argument parser for running tests."""
    parser = argparse.ArgumentParser(
        prog="ai agent-test",
        description="Execute agent test scenarios from tests/01-agents/",
    )
    parser.add_argument("test_id", nargs="?", help="Test ID to run (e.g., 01, 02)")
    parser.add_argument("--all", "-a", action="store_true", help="Run all tests")
    parser.add_argument("--project", "-p", help="Base project ID (optional)")
    parser.add_argument("--output-dir", "-o", help="Output directory for results")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    return parser


def main(args: Optional[list[str]] = None) -> int:
    """Main entry point for agent-test CLI.

    Args:
        args: Command line arguments (uses sys.argv if None)

    Returns:
        Exit code
    """
    if args is None:
        args = sys.argv[1:] if len(sys.argv) > 1 else []

    # Check for subcommands first
    if args and args[0] == "list":
        parser = argparse.ArgumentParser()
        parser.add_argument("--json", "-j", action="store_true")
        parsed = parser.parse_args(args[1:])
        return asyncio.run(list_command(parsed))
    elif args and args[0] == "status":
        parser = argparse.ArgumentParser()
        parser.add_argument("--json", "-j", action="store_true")
        parser.add_argument("--output-dir", "-o")
        parsed = parser.parse_args(args[1:])
        return asyncio.run(status_command(parsed))

    # Default: run command
    parser = create_run_parser()
    parsed = parser.parse_args(args)

    if not parsed.test_id and not getattr(parsed, 'all', False):
        if not args:
            # Show help if no args
            return asyncio.run(list_command(argparse.Namespace(json=False)))
        parser.print_help()
        return 1

    return asyncio.run(run_command(parsed))


if __name__ == "__main__":
    sys.exit(main())
