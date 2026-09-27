"""Integration tests that execute parser example scripts.

This test module runs all parser example scripts to ensure they:
1. Execute without errors
2. Produce expected output
3. Remain up-to-date with code changes

Requirements: 21.3, 21.4, 21.5
"""

import pytest

pytestmark = pytest.mark.integration

import subprocess
import sys
from pathlib import Path
from typing import Tuple

import pytest


# Get project root (go up from tests/parsers/ to project root)
# __file__ is in tests/parsers/, so parent.parent gets us to project root
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Example scripts to test
EXAMPLE_SCRIPTS = [
    "examples/parsers/01_basic_parsing.py",
    "examples/parsers/02_parser_chain.py",
    "examples/parsers/03_cache_and_watcher.py",
    "examples/parsers/04_error_handling.py",
]


def run_example_script(script_path: str) -> Tuple[int, str, str]:
    """Run an example script and return exit code, stdout, and stderr.

    Args:
        script_path: Path to the example script relative to project root

    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    full_path = PROJECT_ROOT / script_path

    if not full_path.exists():
        raise FileNotFoundError(f"Example script not found: {full_path}")

    # Run the script using uv run python
    result = subprocess.run(
        [sys.executable, str(full_path)],
        capture_output=True,
        text=True,
        timeout=60,  # 60 second timeout
        cwd=PROJECT_ROOT,
    )

    return result.returncode, result.stdout, result.stderr


@pytest.mark.parametrize("script_path", EXAMPLE_SCRIPTS)
def test_example_script_runs(script_path: str):
    """Test that example script runs without errors.

    Args:
        script_path: Path to the example script
    """
    exit_code, stdout, stderr = run_example_script(script_path)

    # Print output for debugging
    if exit_code != 0:
        print(f"\n{'=' * 80}")
        print(f"Example script failed: {script_path}")
        print(f"{'=' * 80}")
        print("\nSTDOUT:")
        print(stdout)
        print("\nSTDERR:")
        print(stderr)
        print(f"{'=' * 80}\n")

    # Check exit code
    assert exit_code == 0, (
        f"Example script {script_path} failed with exit code {exit_code}"
    )


@pytest.mark.parametrize("script_path", EXAMPLE_SCRIPTS)
def test_example_script_produces_output(script_path: str):
    """Test that example script produces expected output.

    Args:
        script_path: Path to the example script
    """
    exit_code, stdout, stderr = run_example_script(script_path)

    # Should produce some output
    assert len(stdout) > 0, f"Example script {script_path} produced no output"

    # Should contain section headers (all examples use print_section)
    assert "=" * 80 in stdout, f"Example script {script_path} missing section headers"

    # Should contain summary section
    assert "Summary" in stdout, f"Example script {script_path} missing summary section"


def test_all_examples_exist():
    """Test that all expected example scripts exist."""
    missing_scripts = []

    for script_path in EXAMPLE_SCRIPTS:
        full_path = PROJECT_ROOT / script_path
        if not full_path.exists():
            missing_scripts.append(script_path)

    assert len(missing_scripts) == 0, f"Missing example scripts: {missing_scripts}"


def test_basic_parsing_example_output():
    """Test specific output from basic parsing example."""
    exit_code, stdout, stderr = run_example_script(
        "examples/parsers/01_basic_parsing.py"
    )

    assert exit_code == 0, "Basic parsing example failed"

    # Should mention available parsers
    assert "Available parsers:" in stdout, "Missing parser availability info"

    # Should show parsing examples
    assert "Example" in stdout, "Missing example sections"

    # Should show verification
    assert "Verification:" in stdout or "✓" in stdout, "Missing verification output"


def test_parser_chain_example_output():
    """Test specific output from parser chain example."""
    exit_code, stdout, stderr = run_example_script(
        "examples/parsers/02_parser_chain.py"
    )

    assert exit_code == 0, "Parser chain example failed"

    # Should mention default priority
    assert "Default priority" in stdout or "priority order" in stdout, (
        "Missing priority info"
    )

    # Should demonstrate fallback
    assert "fallback" in stdout.lower(), "Missing fallback demonstration"

    # Should show key takeaways
    assert "Key Takeaways:" in stdout, "Missing key takeaways"


def test_cache_watcher_example_output():
    """Test specific output from cache and watcher example."""
    exit_code, stdout, stderr = run_example_script(
        "examples/parsers/03_cache_and_watcher.py"
    )

    assert exit_code == 0, "Cache and watcher example failed"

    # Should show cache statistics
    assert "Cache Statistics:" in stdout or "cache" in stdout.lower(), (
        "Missing cache info"
    )

    # Should mention hits and misses
    assert "hit" in stdout.lower() or "miss" in stdout.lower(), (
        "Missing cache hit/miss info"
    )


def test_error_handling_example_output():
    """Test specific output from error handling example."""
    exit_code, stdout, stderr = run_example_script(
        "examples/parsers/04_error_handling.py"
    )

    assert exit_code == 0, "Error handling example failed"

    # Should demonstrate error handling
    assert "Error" in stdout or "error" in stdout.lower(), "Missing error handling"

    # Should show graceful degradation
    assert "graceful" in stdout.lower() or "handled" in stdout.lower(), (
        "Missing graceful handling"
    )


def test_examples_are_executable():
    """Test that all example scripts are executable (have shebang)."""
    for script_path in EXAMPLE_SCRIPTS:
        full_path = PROJECT_ROOT / script_path

        with open(full_path, "r") as f:
            first_line = f.readline()

        assert first_line.startswith("#!/usr/bin/env python"), (
            f"Example script {script_path} missing shebang"
        )


def test_examples_have_docstrings():
    """Test that all example scripts have module docstrings."""
    for script_path in EXAMPLE_SCRIPTS:
        full_path = PROJECT_ROOT / script_path

        with open(full_path, "r") as f:
            content = f.read()

        # Should have a docstring after shebang
        assert '"""' in content or "'''" in content, (
            f"Example script {script_path} missing docstring"
        )


def test_examples_reference_requirements():
    """Test that example scripts reference their requirements."""
    for script_path in EXAMPLE_SCRIPTS:
        full_path = PROJECT_ROOT / script_path

        with open(full_path, "r") as f:
            content = f.read()

        # Should reference requirements in docstring
        assert "Requirements:" in content, (
            f"Example script {script_path} missing requirements reference"
        )


@pytest.mark.slow
def test_all_examples_together():
    """Test running all examples in sequence.

    This is a slower test that runs all examples to ensure they work together
    and don't have conflicting side effects.
    """
    results = []

    for script_path in EXAMPLE_SCRIPTS:
        try:
            exit_code, stdout, stderr = run_example_script(script_path)
            results.append((script_path, exit_code == 0, stdout, stderr))
        except Exception as e:
            results.append((script_path, False, "", str(e)))

    # Check all succeeded
    failures = [(path, stderr) for path, success, _, stderr in results if not success]

    if failures:
        print("\n" + "=" * 80)
        print("Failed examples:")
        for path, stderr in failures:
            print(f"\n{path}:")
            print(stderr)
        print("=" * 80)

    assert len(failures) == 0, f"{len(failures)} example(s) failed"


if __name__ == "__main__":
    # Allow running this test file directly
    pytest.main([__file__, "-v"])
