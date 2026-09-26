"""CLI commands for indexing codebases.

Usage:
    ai index [PATH] [--project PROJECT] [--config CONFIG]
    ai index [PATH] --branch BRANCH_NAME
    ai index --prune [--project PROJECT]
    ai index --compact [--project PROJECT]
    ai index --status [--project PROJECT]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional

from agentic_inquiry.cli.env_resolver import load_config_for_environment

logger = logging.getLogger(__name__)


def exit_code_for_index_result(result: Mapping[str, Any]) -> int:
    """Map an indexing result dict to a process exit code.

    Exit 0 only when status is ``completed`` and at least one chunk was
    written. Empty indexes, partial failures, and explicit failure
    statuses return 1 so a crashed embedder cannot look like success.
    """
    status = result.get("status")
    chunks = result.get("chunks_created") or 0
    try:
        chunk_count = int(chunks)
    except (TypeError, ValueError):
        chunk_count = 0
    if status == "completed" and chunk_count > 0:
        return 0
    return 1


async def prune_command(args: argparse.Namespace) -> int:
    """Run expire + prune on stale branch data.

    Soft-deletes chunks for branches no longer discovered by git, then
    hard-deletes chunks whose soft-delete timestamp is older than the
    retention window (branch_max_age_days from config, default 30 days).

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success)
    """
    from agentic_inquiry.storage.facade import StorageFacade
    from agentic_inquiry.indexing.branch_discovery import (
        discover_branches,
        _detect_default_branch,
    )
    from agentic_inquiry.indexing.branch_expiry import (
        expire_stale_branches,
        prune_expired_branches,
    )

    config = load_config_for_environment(args.config)

    project_id = args.project or config.storage.default_project_id
    if not project_id:
        print(
            "Error: No project specified. Use --project or set in config.",
            file=sys.stderr,
        )
        return 1

    project_path = Path(getattr(args, "path", ".")).resolve()
    workspace = str(project_path)

    max_age_days: int = getattr(config.indexing, "branch_max_age_days", 30)
    default_branch: str = _detect_default_branch(workspace)

    print(f"Running branch expiry for project '{project_id}'...")
    print(f"Workspace: {project_path}")
    print(f"Default branch: {default_branch}")
    print(f"Max age days: {max_age_days}")
    print("")

    storage = None
    try:
        storage = await StorageFacade.from_config(config, project_id)

        # Discover active branches
        discovered = discover_branches(
            workspace, max_age_days=max_age_days, default_branch=default_branch
        )
        active_branches: set[str] = {b.short_name for b in discovered}
        logger.info("Active branches discovered: %s", active_branches)

        # Soft-delete stale branches
        expired = await expire_stale_branches(
            storage=storage,
            project_id=project_id,
            active_branches=active_branches,
            default_branch=default_branch,
        )
        if expired:
            print(f"Expired branches ({len(expired)}): {', '.join(sorted(expired))}")
        else:
            print("No branches to expire.")

        # Hard-delete past retention window
        retention_days: int = getattr(config.indexing, "branch_max_age_days", 30)
        pruned_count = await prune_expired_branches(
            storage=storage,
            project_id=project_id,
            retention_days=retention_days,
        )
        print(
            f"Pruned {pruned_count} chunks past the {retention_days}-day retention window."
        )

        return 0

    except Exception as e:
        logger.exception("Prune command failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1

    finally:
        if storage is not None:
            try:
                await storage.close()
            except Exception as close_err:
                logger.warning("Error closing storage: %s", close_err)


async def compact_command(args: argparse.Namespace) -> int:
    """Run LanceDB compaction and version cleanup on all tables.

    Merges small fragment files into larger ones (compact_files) and then
    removes old MVCC versions (cleanup_old_versions).  This is the manual
    trigger for operators who want to reclaim disk space outside of the
    automatic post-indexing maintenance.

    Only meaningful when the storage backend is LanceDB.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success)
    """
    config = load_config_for_environment(args.config)

    project_id = args.project or config.storage.default_project_id
    if not project_id:
        print(
            "Error: No project specified. Use --project or set in config.",
            file=sys.stderr,
        )
        return 1

    from agentic_inquiry.storage.facade import StorageFacade

    storage = None
    try:
        storage = await StorageFacade.from_config(config, project_id)

        if storage.get_backend_type() != "lancedb":
            print(
                f"Compaction is only supported for the LanceDB backend "
                f"(current backend: {storage.get_backend_type()}).",
                file=sys.stderr,
            )
            return 1

        db_manager = storage.get_db_manager()

        print("Running LanceDB compaction and cleanup...")
        result = await db_manager.run_maintenance()

        summary = result.get("summary", {})
        print("=" * 50)
        print("COMPACTION COMPLETE")
        print("=" * 50)
        print(f"Fragments reduced:  {summary.get('fragments_reduced', 0):,}")
        print(f"Versions removed:   {summary.get('versions_removed', 0):,}")
        print(f"Compaction success: {result.get('compact_success', False)}")
        print(f"Cleanup success:    {result.get('cleanup_success', False)}")
        return 0

    except Exception as e:
        logger.exception("Compaction failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1

    finally:
        if storage is not None:
            try:
                await storage.close()
            except Exception as close_err:
                logger.warning("Error closing storage: %s", close_err)


async def index_command(args: argparse.Namespace) -> int:
    """Execute indexing command.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success)
    """
    from agentic_inquiry.storage.facade import StorageFacade
    from agentic_inquiry.indexing.pipeline import IndexingPipeline

    config = load_config_for_environment(args.config)

    # --prune flag: run expiry/prune then return
    if getattr(args, "prune", False):
        return await prune_command(args)

    # --compact flag: run LanceDB maintenance then return
    if getattr(args, "compact", False):
        return await compact_command(args)

    project_id = args.project or config.storage.default_project_id
    if not project_id:
        print(
            "Error: No project specified. Use --project or set in config.",
            file=sys.stderr,
        )
        return 1

    project_path = Path(args.path).resolve()
    if not project_path.exists():
        print(f"Error: Path does not exist: {project_path}", file=sys.stderr)
        return 1

    # Onboard gate check
    skip_onboard = getattr(args, "skip_onboard_check", False)
    try:
        from agentic_inquiry.onboard.metadata_service import OnboardMetadataService
        from agentic_inquiry.onboard.gate import check_onboard_gate, OnboardGateError

        metadata_svc = await OnboardMetadataService.from_config(
            config,
            workspace=str(project_path),
            project_id=project_id,
        )
        try:
            await check_onboard_gate(
                metadata_svc,
                project_path,
                config,
                skip_gate=skip_onboard,
            )
        except OnboardGateError as e:
            print(f"\n{e}", file=sys.stderr)
            return 1
        finally:
            await metadata_svc.close()
    except ImportError:
        logger.debug("Onboard gate check unavailable (missing dependencies)")
    except Exception as e:
        logger.warning("Onboard gate check failed: %s", e)

    # Determine branch to index
    branch_name: str = getattr(args, "branch", None) or "main"

    print(f"Indexing project '{project_id}'...")
    print(f"Path: {project_path}")
    print(f"Branch: {branch_name}")
    print("")

    storage = None
    worktree_path: Optional[Path] = None
    try:
        # If --branch is specified (not the checked-out branch), use git worktree
        # to index that branch without disturbing the working tree.
        index_path = project_path
        if getattr(args, "branch", None):
            worktree_dir = tempfile.mkdtemp(
                prefix=f"ai_worktree_{branch_name.replace('/', '_')}_"
            )
            worktree_path = Path(worktree_dir)
            logger.info(
                "Creating git worktree for branch %r at %s", branch_name, worktree_path
            )
            result_wt = subprocess.run(
                ["git", "worktree", "add", "--detach", str(worktree_path), branch_name],
                capture_output=True,
                text=True,
                cwd=str(project_path),
            )
            if result_wt.returncode != 0:
                print(
                    f"Error: git worktree add failed for branch '{branch_name}': "
                    f"{result_wt.stderr.strip()}",
                    file=sys.stderr,
                )
                return 1
            index_path = worktree_path

        # Configure embedder based on storage backend capabilities
        from agentic_inquiry.embeddings.factory import configure_embedder_for_backend

        configure_embedder_for_backend(config, quiet=getattr(args, "quiet", False))

        storage = await StorageFacade.from_config(config, project_id)
        pipeline = IndexingPipeline(
            storage,
            config,
            project_id,
            project_root=str(index_path),
        )
        if not args.quiet:
            print("Starting indexing (this may take a while)...")

        # Run indexing synchronously
        result = await pipeline.index_directory(
            path=str(index_path),
            wait=True,
        )

        print("")
        print("=" * 50)
        print("INDEXING COMPLETE")
        print("=" * 50)
        print(f"Status: {result.get('status', 'unknown')}")
        print(f"Files processed: {result.get('files_processed', 0)}")
        print(f"Files failed: {result.get('files_failed', 0)}")
        print(f"Chunks created: {result.get('chunks_created', 0)}")
        print(f"Entities created: {result.get('entities_created', 0)}")
        if result.get("message"):
            print(f"Message: {result['message']}")

        # Show errors if present
        errors = result.get("errors", [])
        if errors:
            print(f"\nErrors ({len(errors)}):")
            for err in errors[:5]:  # Show first 5 errors
                print(
                    f"  - {err.get('file', 'unknown')}: {err.get('message', 'Unknown error')}"
                )
            if len(errors) > 5:
                print(f"  ... and {len(errors) - 5} more errors")

        return exit_code_for_index_result(result)

    except Exception as e:
        logger.exception("Indexing failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1

    finally:
        if storage is not None:
            try:
                await storage.close()
            except Exception as close_err:
                logger.warning("Error closing storage: %s", close_err)
        # Remove the temporary git worktree if one was created
        if worktree_path is not None:
            try:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(worktree_path)],
                    capture_output=True,
                    cwd=str(project_path),
                )
                logger.info("Removed git worktree at %s", worktree_path)
            except Exception as wt_err:
                logger.warning(
                    "Failed to remove git worktree %s: %s", worktree_path, wt_err
                )


async def status_command(args: argparse.Namespace) -> int:
    """Show index status.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success)
    """
    from agentic_inquiry.storage.facade import StorageFacade

    config = load_config_for_environment(args.config)

    project_id = args.project or config.storage.default_project_id
    if not project_id:
        print(
            "Error: No project specified. Use --project or set in config.",
            file=sys.stderr,
        )
        return 1

    storage = None
    try:
        storage = await StorageFacade.from_config(config, project_id)

        # Get counts using proper facade methods
        chunk_count = await storage.count_chunks()
        entity_count = await storage.count_entities()
        rel_count = await storage.count_relationships()

        print("=" * 50)
        print(f"INDEX STATUS: {project_id}")
        print("=" * 50)
        print(f"Chunks:        {chunk_count:,}")
        print(f"Entities:      {entity_count:,}")
        print(f"Relationships: {rel_count:,}")

        return 0

    except Exception as e:
        logger.exception("Status check failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1

    finally:
        if storage is not None:
            try:
                await storage.close()
            except Exception as close_err:
                logger.warning("Error closing storage: %s", close_err)


def create_index_parser() -> argparse.ArgumentParser:
    """Create parser for index command."""
    parser = argparse.ArgumentParser(
        prog="ai index",
        description="Index a codebase for semantic search and analysis",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to index (default: current directory)",
    )
    parser.add_argument(
        "--project",
        "-p",
        help="Project ID (uses config default if not specified)",
    )
    parser.add_argument(
        "--config",
        "-c",
        help="Path to configuration file",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress output",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed error information",
    )
    parser.add_argument(
        "--skip-onboard-check",
        action="store_true",
        default=False,
        help="Skip the missing-onboard warning",
    )
    parser.add_argument(
        "--branch",
        metavar="BRANCH_NAME",
        help=(
            "Index a specific branch using git worktree (e.g. feature/my-branch). "
            "Creates a temporary worktree so the current checkout is not disturbed."
        ),
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        default=False,
        help=(
            "Expire stale branches and hard-delete chunks past the retention window. "
            "Uses branch_max_age_days from config (default: 30)."
        ),
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        default=False,
        help=(
            "Run LanceDB compaction and old-version cleanup on all tables. "
            "Reclaims disk space without re-indexing. LanceDB backend only."
        ),
    )
    return parser


def create_status_parser() -> argparse.ArgumentParser:
    """Create parser for status command."""
    parser = argparse.ArgumentParser(
        prog="ai index status",
        description="Show index status",
    )
    parser.add_argument(
        "--project",
        "-p",
        help="Project ID",
    )
    parser.add_argument(
        "--config",
        "-c",
        help="Path to configuration file",
    )
    return parser


def main(args: Optional[list[str]] = None) -> int:
    """Main entry point for index CLI.

    Args:
        args: Command line arguments (uses sys.argv if None)

    Returns:
        Exit code
    """
    if args is None:
        args = sys.argv[1:] if len(sys.argv) > 1 else []

    # Check for status subcommand
    if args and args[0] == "status":
        parser = create_status_parser()
        parsed = parser.parse_args(args[1:])
        return asyncio.run(status_command(parsed))

    # Default: index command
    parser = create_index_parser()
    parsed = parser.parse_args(args)
    return asyncio.run(index_command(parsed))


if __name__ == "__main__":
    sys.exit(main())
