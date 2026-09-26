"""Staleness detection for onboard documentation.

Computes whether onboard documentation is stale based on:
- Days elapsed since last onboard
- File changes since last onboard (via git diff)
- Commits since last onboard (via git rev-list)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agentic_inquiry.config import Config
    from agentic_inquiry.onboard.metadata_service import OnboardMetadataService

logger = logging.getLogger(__name__)

# Default thresholds
DEFAULT_DAYS_THRESHOLD = 7
DEFAULT_FILES_THRESHOLD = 10
DEFAULT_COMMITS_THRESHOLD = 5


@dataclass
class StalenessResult:
    """Result of a staleness check.

    Attributes:
        is_stale: Whether the documentation is considered stale.
        reason: Primary reason for staleness.
        days_since_onboard: Days since last onboard.
        files_changed: Files changed since last onboard.
        commits_since_onboard: Commits since last onboard.
        last_onboard_date: ISO date of last onboard.
        message: Human-readable explanation.
    """

    is_stale: bool
    reason: Optional[str]  # "no_onboard" | "days_elapsed" | "file_changes" | "commits"
    days_since_onboard: Optional[int]
    files_changed: Optional[int]
    commits_since_onboard: Optional[int]
    last_onboard_date: Optional[str]
    message: str


async def check_onboard_staleness(
    metadata_service: "OnboardMetadataService",
    workspace: Path,
    config: Optional["Config"] = None,
) -> StalenessResult:
    """Check if onboard documentation is stale.

    Args:
        metadata_service: Service for accessing onboard metadata.
        workspace: Project workspace path (for git operations).
        config: Configuration with staleness thresholds. Uses defaults if None.

    Returns:
        StalenessResult with staleness determination.
    """
    latest = await metadata_service.get_latest_onboard()

    if not latest:
        return StalenessResult(
            is_stale=True,
            reason="no_onboard",
            days_since_onboard=None,
            files_changed=None,
            commits_since_onboard=None,
            last_onboard_date=None,
            message=(
                "No onboard documentation exists for this project. "
                "Run /ai:onboard to create baseline documentation."
            ),
        )

    now = datetime.now(timezone.utc)
    # Make naive timestamps tz-aware for comparison
    ts = (
        latest.timestamp
        if latest.timestamp.tzinfo
        else latest.timestamp.replace(tzinfo=timezone.utc)
    )
    days_elapsed = (now - ts).days

    files_changed = 0
    commits_since = 0
    git_available = bool(latest.commit_sha)
    if latest.commit_sha:
        files_changed = await _count_changed_files(workspace, latest.commit_sha)
        commits_since = await _count_commits_since(workspace, latest.commit_sha)
        # If git returned 0 for both but commit_sha existed, verify git is working
        if files_changed == 0 and commits_since == 0:
            git_available = await _is_git_available(workspace)

    # Thresholds from config or defaults
    days_threshold = DEFAULT_DAYS_THRESHOLD
    files_threshold = DEFAULT_FILES_THRESHOLD
    commits_threshold = DEFAULT_COMMITS_THRESHOLD

    if config is not None:
        onboard_cfg = getattr(config, "onboard", None)
        if onboard_cfg:
            staleness_cfg = getattr(onboard_cfg, "staleness", None)
            if staleness_cfg:
                days_threshold = getattr(
                    staleness_cfg, "days_threshold", days_threshold
                )
                files_threshold = getattr(
                    staleness_cfg, "files_threshold", files_threshold
                )
                commits_threshold = getattr(
                    staleness_cfg, "commits_threshold", commits_threshold
                )

    is_stale = False
    reason: Optional[str] = None
    message_parts: list[str] = []

    if days_elapsed > days_threshold:
        is_stale = True
        reason = "days_elapsed"
        message_parts.append(
            f"{days_elapsed} days since last onboard (threshold: {days_threshold})"
        )

    if files_changed > files_threshold:
        is_stale = True
        if not reason:
            reason = "file_changes"
        message_parts.append(
            f"{files_changed} files changed since last onboard (threshold: {files_threshold})"
        )

    if commits_since > commits_threshold:
        is_stale = True
        if not reason:
            reason = "commits"
        message_parts.append(
            f"{commits_since} commits since last onboard (threshold: {commits_threshold})"
        )

    if is_stale:
        message = (
            "Onboard documentation is stale:\n"
            + "\n".join(f"- {part}" for part in message_parts)
            + "\n\nConsider running /ai:onboard to refresh documentation."
        )
    else:
        git_note = (
            "" if git_available else " (git unavailable, change detection skipped)"
        )
        message = (
            f"Onboard documentation is current "
            f"({days_elapsed} days old, {files_changed} files changed, "
            f"{commits_since} commits since last onboard).{git_note}"
        )

    return StalenessResult(
        is_stale=is_stale,
        reason=reason,
        days_since_onboard=days_elapsed,
        files_changed=files_changed,
        commits_since_onboard=commits_since,
        last_onboard_date=latest.timestamp.isoformat(),
        message=message,
    )


async def _count_changed_files(workspace: Path, since_commit: str) -> int:
    """Count files changed since commit via git diff --numstat."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "diff",
            "--numstat",
            f"{since_commit}..HEAD",
            cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode != 0:
            return 0

        lines = stdout.decode().strip().split("\n")
        return len([line for line in lines if line.strip()])

    except Exception as e:
        logger.warning("Failed to count changed files: %s", e)
        return 0


async def _count_commits_since(workspace: Path, since_commit: str) -> int:
    """Count commits since commit via git rev-list."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "rev-list",
            "--count",
            f"{since_commit}..HEAD",
            cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode != 0:
            return 0

        return int(stdout.decode().strip())

    except Exception as e:
        logger.warning("Failed to count commits: %s", e)
        return 0


async def _is_git_available(workspace: Path) -> bool:
    """Check if git is functional in workspace."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "rev-parse",
            "--git-dir",
            cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0
    except Exception:
        return False
