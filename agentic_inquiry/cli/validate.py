"""CLI commands for index validation.

Usage:
    ai validate [--sample-size N] [--deep] [--json] [--project PROJECT]
    ai validate check <check_name> [--sample-size N]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from agentic_inquiry.cli.env_resolver import load_config_for_environment
from agentic_inquiry.validation import AccuracyValidator, ValidationReport

logger = logging.getLogger(__name__)


def format_report(report: ValidationReport, verbose: bool = False) -> str:
    """Format validation report for display.

    Args:
        report: ValidationReport to format
        verbose: Include detailed failure information

    Returns:
        Formatted string representation
    """
    lines = []
    lines.append("=" * 60)
    lines.append("INDEX VALIDATION REPORT")
    lines.append("=" * 60)
    lines.append(f"Project: {report.project_id}")
    lines.append(f"Threshold: {report.threshold * 100:.0f}%")
    lines.append("")

    # Overall result
    status_icon = "✓" if report.meets_threshold else "✗"
    status_color = "\033[32m" if report.meets_threshold else "\033[31m"
    reset = "\033[0m"

    lines.append(f"Overall Accuracy: {status_color}{report.overall_accuracy * 100:.1f}%{reset}")
    lines.append(f"Status: {status_color}{status_icon} {'PASSED' if report.meets_threshold else 'FAILED'}{reset}")
    lines.append(f"Checks: {report.passed_checks}/{report.total_checks} passed")
    lines.append("")

    # Detected stack
    if report.detected_stack:
        frameworks = report.detected_stack.get("frameworks", [])
        languages = report.detected_stack.get("languages", [])
        if frameworks:
            lines.append(f"Frameworks: {', '.join(frameworks)}")
        if languages:
            lines.append(f"Languages: {', '.join(languages)}")
        lines.append("")

    # Individual checks
    lines.append("┌─ CHECKS ─" + "─" * 48)
    for result in report.results:
        status = "✓" if result.passed else "✗"
        accuracy_str = f"{result.accuracy * 100:.1f}%"
        checked_str = f"({result.valid_count}/{result.total_checked})"

        lines.append(
            f"│ {status} {result.check_name:<25} {accuracy_str:>6} {checked_str:>12}"
        )

        if verbose and result.details:
            for detail in result.details[:5]:
                lines.append(f"│   └─ {detail}")
            if len(result.details) > 5:
                lines.append(f"│   └─ ... and {len(result.details) - 5} more")

    lines.append("└" + "─" * 58)

    # Errors
    if report.errors:
        lines.append("")
        lines.append("⚠ ERRORS:")
        for error in report.errors:
            lines.append(f"  • {error}")

    return "\n".join(lines)


async def validate_command(args: argparse.Namespace) -> int:
    """Execute validation command.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success/passed, 1 for failed)
    """
    from agentic_inquiry.storage.facade import StorageFacade

    config = load_config_for_environment()

    # Determine project_id from args or config
    project_id = args.project or config.storage.default_project_id
    if not project_id:
        print("Error: No project specified. Use --project or set in config.", file=sys.stderr)
        return 1

    # Determine project root
    project_root = Path(args.path).resolve() if args.path else Path.cwd()

    print(f"Validating index for project '{project_id}'...")
    print(f"Project root: {project_root}")
    print(f"Sample size: {args.sample_size}")
    if args.deep:
        print("Running deep completeness check...")
    print("")

    try:
        storage = await StorageFacade.from_config(config, project_id)
        validator = AccuracyValidator(
            storage=storage,
            project_root=project_root,
            threshold=args.threshold / 100.0,
        )

        report = await validator.validate_all(
            sample_size=args.sample_size,
            deep=args.deep,
        )

        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(format_report(report, verbose=args.verbose))

        # Return exit code based on threshold
        return 0 if report.meets_threshold else 1

    except Exception as e:
        logger.exception("Validation failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for validate commands."""
    parser = argparse.ArgumentParser(
        prog="ai validate",
        description="Validate index accuracy against threshold",
    )

    parser.add_argument(
        "--sample-size", "-s",
        type=int,
        default=100,
        help="Number of samples per validation check (default: 100)",
    )
    parser.add_argument(
        "--deep", "-d",
        action="store_true",
        help="Run deep completeness check (slower)",
    )
    parser.add_argument(
        "--threshold", "-t",
        type=float,
        default=95.0,
        help="Accuracy threshold percentage (default: 95)",
    )
    parser.add_argument(
        "--project", "-p",
        help="Project ID (uses config default if not specified)",
    )
    parser.add_argument(
        "--path",
        help="Project root path (default: current directory)",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed failure information",
    )

    return parser


def main(args: Optional[list[str]] = None) -> int:
    """Main entry point for validate CLI.

    Args:
        args: Command line arguments (uses sys.argv if None)

    Returns:
        Exit code
    """
    parser = create_parser()
    parsed = parser.parse_args(args)

    # Run async command
    return asyncio.run(validate_command(parsed))


if __name__ == "__main__":
    sys.exit(main())
