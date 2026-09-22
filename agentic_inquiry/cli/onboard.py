"""CLI commands for onboard run metadata.

Usage:
    ai onboard start [--project PROJECT] [--artifact-path PATH]
    ai onboard complete --run-id ID [--project PROJECT]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

from agentic_inquiry.cli.env_resolver import load_config_for_environment

logger = logging.getLogger(__name__)


async def start_command(args: argparse.Namespace) -> int:
    """Record a pending onboard run and print its id."""
    from agentic_inquiry.onboard.metadata_service import OnboardMetadataService

    config = load_config_for_environment()
    project_id = args.project or getattr(config.storage, "default_project_id", None)

    workspace = str(Path.cwd())
    artifact_path = args.artifact_path or workspace
    service = await OnboardMetadataService.from_config(
        config,
        workspace=workspace,
        project_id=project_id,
    )
    try:
        run = await service.create_onboard_run(artifact_path=artifact_path)
        print(f"ONBOARD_RUN_ID={run.run_id}")
        return 0
    except Exception as e:
        logger.exception("Failed to start onboard run")
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        await service.close()


async def complete_command(args: argparse.Namespace) -> int:
    """Mark an onboard run completed and latest."""
    from agentic_inquiry.onboard.metadata_service import OnboardMetadataService

    config = load_config_for_environment()
    project_id = args.project or getattr(config.storage, "default_project_id", None)

    workspace = str(Path.cwd())
    service = await OnboardMetadataService.from_config(
        config,
        workspace=workspace,
        project_id=project_id,
    )
    try:
        await service.complete_onboard_run(run_id=args.run_id)
        print(f"Completed onboard run {args.run_id}")
        return 0
    except Exception as e:
        logger.exception("Failed to complete onboard run")
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        await service.close()


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for onboard commands."""
    parser = argparse.ArgumentParser(
        prog="ai onboard",
        description="Record onboard documentation runs",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Onboard commands")

    start_parser = subparsers.add_parser(
        "start",
        help="Start an onboard run and print ONBOARD_RUN_ID",
    )
    start_parser.add_argument(
        "--project",
        "-p",
        help="Project ID",
    )
    start_parser.add_argument(
        "--artifact-path",
        help="Path to store onboard artifacts (default: current directory)",
    )
    start_parser.set_defaults(func=start_command)

    complete_parser = subparsers.add_parser(
        "complete",
        help="Mark an onboard run as completed",
    )
    complete_parser.add_argument(
        "--run-id",
        required=True,
        help="Run id printed by ai onboard start",
    )
    complete_parser.add_argument(
        "--project",
        "-p",
        help="Project ID",
    )
    complete_parser.set_defaults(func=complete_command)

    return parser


def main(args: Optional[list[str]] = None) -> int:
    """Main entry point for onboard CLI."""
    parser = create_parser()
    parsed = parser.parse_args(args)

    if not parsed.subcommand:
        parser.print_help()
        return 1

    return asyncio.run(parsed.func(parsed))


if __name__ == "__main__":
    sys.exit(main())
