"""Interactive setup wizard for Agentic Inquiry.

This module provides the main entry point for the setup wizard, routing to
appropriate backend-specific handlers based on command-line arguments.

Usage:
    ai setup                  # Interactive mode - prompts for backend type
    ai setup local [name]     # LanceDB (local)
    ai setup --dev            # Create test environment

Environment Naming:
    - Default: 'ai' (production)
    - With --dev: 'ai-test' or 'ai-test-<name>'
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from agentic_inquiry.cli.setup.base import (
    prompt_choice,
    print_error,
    print_info,
)
from agentic_inquiry.cli.setup.local_setup import LocalSetup


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for setup command.

    Returns:
        Configured ArgumentParser
    """
    parser = argparse.ArgumentParser(
        description="Configure Agentic Inquiry storage backend",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ai setup                    Interactive mode
  ai setup local              LanceDB (local, default)
""",
    )

    parser.add_argument(
        "backend",
        nargs="?",
        choices=["local"],
        help="Backend type: local (LanceDB)",
    )

    parser.add_argument(
        "name",
        nargs="?",
        help="Environment name (default: 'ai' or 'ai-test' with --dev)",
    )

    parser.add_argument(
        "--dev",
        action="store_true",
        help="Create a test/development environment",
    )

    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Workspace root path (default: current directory)",
    )

    return parser


def run_interactive_setup(
    is_dev: bool = False,
    workspace: Optional[Path] = None,
) -> bool:
    """Run interactive setup when no backend type is specified.

    Args:
        is_dev: Whether to create a test environment
        workspace: Workspace root path

    Returns:
        True if setup completed successfully
    """
    print("========================================")
    print("  Agentic Inquiry Environment Setup")
    print("========================================")

    print_info("Select the storage backend for your environment.")
    print_info("")
    print_info("LanceDB (Local) - Best for development")
    print_info("  - No external dependencies")
    print_info("  - Fast, embedded vector database")
    print_info("  - SQLite for metadata")
    print_info("")
    prompt_choice("\nSelect storage backend:", ["LanceDB (Local)"])

    setup = LocalSetup(is_dev=is_dev, workspace=workspace)

    return setup.run()


def run_setup(args: Optional[list[str]] = None) -> bool:
    """Run the setup wizard with the given arguments.

    Args:
        args: Command-line arguments (defaults to sys.argv[1:])

    Returns:
        True if setup completed successfully
    """
    parser = create_parser()
    parsed = parser.parse_args(args)

    workspace = parsed.workspace or Path.cwd()
    is_dev = parsed.dev

    # If no backend specified, run interactive mode
    if not parsed.backend:
        return run_interactive_setup(is_dev=is_dev, workspace=workspace)

    # Route to appropriate handler based on backend type
    if parsed.backend == "local":
        setup = LocalSetup(
            env_name=parsed.name,
            is_dev=is_dev,
            workspace=workspace,
        )
        return setup.run()

    else:
        print_error(f"Unknown backend: {parsed.backend}")
        return False


# Legacy entry point for backward compatibility
def run_setup_legacy() -> None:
    """Legacy entry point - runs interactive setup.

    This function maintains backward compatibility with the old setup wizard
    that only supported interactive mode.
    """
    success = run_setup()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    success = run_setup()
    sys.exit(0 if success else 1)
