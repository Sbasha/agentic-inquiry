"""Discover branches eligible for indexing."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("ai.indexing.branch_discovery")


@dataclass
class DiscoveredBranch:
    """A branch discovered for indexing."""

    name: str
    short_name: str
    last_commit_date: datetime
    last_commit_sha: str
    is_default: bool = False


def discover_branches(
    workspace: str,
    max_age_days: int = 30,
    default_branch: str | None = None,
) -> list[DiscoveredBranch]:
    """Discover remote branches eligible for indexing.

    Uses git branch -r --sort=-committerdate to list remote branches
    sorted by last commit date, filtered by age cutoff.

    Args:
        workspace: Git repository root path.
        max_age_days: Only include branches with commits within this many days.
        default_branch: Name of the default branch (auto-detected if None).

    Returns:
        List of branches eligible for indexing.
    """
    if default_branch is None:
        default_branch = _detect_default_branch(workspace)

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    try:
        result = subprocess.run(
            [
                "git",
                "branch",
                "-r",
                "--sort=-committerdate",
                "--format=%(refname:short)\t%(committerdate:iso-strict)\t%(objectname:short)",
            ],
            capture_output=True,
            text=True,
            cwd=workspace,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("git branch -r failed: %s", result.stderr.strip())
            return []

        branches: list[DiscoveredBranch] = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue

            ref_name = parts[0].strip()
            date_str = parts[1].strip()
            sha = parts[2].strip()

            if "HEAD" in ref_name:
                continue

            commit_date = datetime.fromisoformat(date_str)
            if commit_date.tzinfo is None:
                commit_date = commit_date.replace(tzinfo=timezone.utc)

            short_name = ref_name
            if "/" in ref_name:
                short_name = ref_name.split("/", 1)[1]

            is_default = short_name in (default_branch, f"origin/{default_branch}")

            if not is_default and commit_date < cutoff:
                continue

            branches.append(
                DiscoveredBranch(
                    name=ref_name,
                    short_name=short_name,
                    last_commit_date=commit_date,
                    last_commit_sha=sha,
                    is_default=is_default,
                )
            )

        return branches

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("Branch discovery failed: %s", e)
        return []


def _detect_default_branch(workspace: str) -> str:
    """Detect the default branch name (main or master)."""
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD", "--short"],
            capture_output=True,
            text=True,
            cwd=workspace,
            timeout=5,
        )
        if result.returncode == 0:
            ref = result.stdout.strip()
            return ref.split("/", 1)[-1] if "/" in ref else ref
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "main"
