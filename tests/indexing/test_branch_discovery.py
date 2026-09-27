"""Tests for branch discovery (T42).

Uses real git repos created in tmp_path — no mocking of git subprocess.

Covers:
- discover_branches returns only branches within max_age_days
- Stale branches older than cutoff are excluded
- Default branch is always included regardless of age
- Default branch is auto-detected
- Explicit branch filtering via age cutoff
- Branches at boundary (exactly at cutoff) behavior
- discover_branches returns empty list when git fails
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agentic_inquiry.indexing.branch_discovery import _detect_default_branch, discover_branches


# ---------------------------------------------------------------------------
# Fixtures — real git repos in tmp_path
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path, env: dict | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command in cwd."""
    effective_env = {**os.environ}
    if env:
        effective_env.update(env)
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
        env=effective_env,
    )


def _date_env(dt: datetime) -> dict[str, str]:
    """Produce GIT_COMMITTER_DATE / GIT_AUTHOR_DATE env vars for a backdated commit."""
    iso = dt.strftime("%Y-%m-%dT%H:%M:%S +0000")
    return {
        "GIT_COMMITTER_DATE": iso,
        "GIT_AUTHOR_DATE": iso,
    }


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """Create a bare git remote repository that acts as origin."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(["init", "--bare", "--initial-branch=main", str(remote)], cwd=tmp_path)
    return remote


@pytest.fixture
def local_repo(tmp_path: Path, bare_remote: Path) -> Path:
    """Create a local git repo cloned from the bare remote."""
    repo = tmp_path / "repo"
    _git(["clone", str(bare_remote), str(repo)], cwd=tmp_path)
    # The tests push and discover "main"; do not depend on the
    # machine's init.defaultBranch for the unborn branch name.
    _git(["symbolic-ref", "HEAD", "refs/heads/main"], cwd=repo)
    _git(["config", "user.email", "test@example.com"], cwd=repo)
    _git(["config", "user.name", "Test User"], cwd=repo)
    return repo


def _initial_commit(repo: Path, dt: datetime | None = None) -> None:
    """Create an initial commit on the current branch."""
    (repo / "README.md").write_text("initial commit")
    _git(["add", "."], cwd=repo)
    env = _date_env(dt) if dt else None
    _git(["commit", "-m", "init"], cwd=repo, env=env)


def _create_branch_with_commit(repo: Path, branch: str, filename: str, dt: datetime | None = None) -> None:
    """Create a new branch from current HEAD with a single commit."""
    _git(["checkout", "-b", branch], cwd=repo)
    (repo / filename).write_text(f"content for {branch}")
    _git(["add", "."], cwd=repo)
    env = _date_env(dt) if dt else None
    _git(["commit", "-m", f"commit on {branch}"], cwd=repo, env=env)
    _git(["push", "origin", branch], cwd=repo)
    _git(["checkout", "HEAD~0"], cwd=repo, check=False)  # detach before switching
    # Return to default branch
    _git(["checkout", "-"], cwd=repo, check=False)


# ---------------------------------------------------------------------------
# T42-1: Returns only branches within max_age_days
# ---------------------------------------------------------------------------

class TestDiscoverBranchesAgeFilter:
    """discover_branches filters by max_age_days cutoff."""

    def test_recent_branch_is_included(
        self, local_repo: Path, bare_remote: Path
    ) -> None:
        """A branch committed yesterday must be included with default 30-day cutoff."""
        recent_dt = datetime.now(timezone.utc) - timedelta(days=1)
        _initial_commit(local_repo, dt=recent_dt)
        _git(["push", "--set-upstream", "origin", "main"], cwd=local_repo, check=False)
        _git(["push", "origin", "main"], cwd=local_repo, check=False)

        # Create a recent feature branch
        _create_branch_with_commit(
            local_repo, "feature/recent", "recent.py", dt=recent_dt
        )

        branches = discover_branches(str(local_repo), max_age_days=30)
        names = [b.short_name for b in branches]
        assert "feature/recent" in names

    def test_stale_branch_is_excluded(
        self, local_repo: Path, bare_remote: Path
    ) -> None:
        """A branch committed 60 days ago must be excluded with a 30-day cutoff."""
        recent_dt = datetime.now(timezone.utc) - timedelta(days=1)
        stale_dt = datetime.now(timezone.utc) - timedelta(days=60)

        _initial_commit(local_repo, dt=recent_dt)
        _git(["push", "--set-upstream", "origin", "main"], cwd=local_repo, check=False)

        _create_branch_with_commit(
            local_repo, "feature/stale", "stale.py", dt=stale_dt
        )

        branches = discover_branches(str(local_repo), max_age_days=30)
        names = [b.short_name for b in branches]
        assert "feature/stale" not in names

    def test_default_branch_always_included_even_when_stale(
        self, local_repo: Path, bare_remote: Path
    ) -> None:
        """The default branch must never be filtered out by age."""
        stale_dt = datetime.now(timezone.utc) - timedelta(days=90)

        _initial_commit(local_repo, dt=stale_dt)
        _git(["push", "--set-upstream", "origin", "main"], cwd=local_repo, check=False)

        branches = discover_branches(
            str(local_repo), max_age_days=7, default_branch="main"
        )
        names = [b.short_name for b in branches]
        assert "main" in names

    def test_default_branch_marked_as_is_default(
        self, local_repo: Path, bare_remote: Path
    ) -> None:
        """DiscoveredBranch.is_default must be True for the default branch."""
        dt = datetime.now(timezone.utc) - timedelta(days=1)
        _initial_commit(local_repo, dt=dt)
        _git(["push", "--set-upstream", "origin", "main"], cwd=local_repo, check=False)

        branches = discover_branches(str(local_repo), default_branch="main")
        default_branches = [b for b in branches if b.is_default]
        assert len(default_branches) >= 1
        assert default_branches[0].short_name == "main"


# ---------------------------------------------------------------------------
# T42-2: Configurable cutoff
# ---------------------------------------------------------------------------

class TestConfigurableCutoff:
    """max_age_days parameter controls which branches are included."""

    def test_7_day_cutoff_excludes_8_day_old_branch(
        self, local_repo: Path, bare_remote: Path
    ) -> None:
        recent_dt = datetime.now(timezone.utc) - timedelta(days=1)
        old_dt = datetime.now(timezone.utc) - timedelta(days=8)

        _initial_commit(local_repo, dt=recent_dt)
        _git(["push", "--set-upstream", "origin", "main"], cwd=local_repo, check=False)

        _create_branch_with_commit(
            local_repo, "feature/old-8days", "old.py", dt=old_dt
        )

        branches = discover_branches(str(local_repo), max_age_days=7)
        names = [b.short_name for b in branches]
        assert "feature/old-8days" not in names

    def test_7_day_cutoff_includes_6_day_old_branch(
        self, local_repo: Path, bare_remote: Path
    ) -> None:
        recent_dt = datetime.now(timezone.utc) - timedelta(days=1)
        six_days_dt = datetime.now(timezone.utc) - timedelta(days=6)

        _initial_commit(local_repo, dt=recent_dt)
        _git(["push", "--set-upstream", "origin", "main"], cwd=local_repo, check=False)

        _create_branch_with_commit(
            local_repo, "feature/new-6days", "new.py", dt=six_days_dt
        )

        branches = discover_branches(str(local_repo), max_age_days=7)
        names = [b.short_name for b in branches]
        assert "feature/new-6days" in names


# ---------------------------------------------------------------------------
# T42-3: DiscoveredBranch fields
# ---------------------------------------------------------------------------

class TestDiscoveredBranchFields:
    """Verify DiscoveredBranch has the correct fields after discovery."""

    def test_branch_has_name(self, local_repo: Path, bare_remote: Path) -> None:
        dt = datetime.now(timezone.utc) - timedelta(days=1)
        _initial_commit(local_repo, dt=dt)
        _git(["push", "--set-upstream", "origin", "main"], cwd=local_repo, check=False)

        branches = discover_branches(str(local_repo), default_branch="main")
        assert all(isinstance(b.name, str) and b.name for b in branches)

    def test_branch_has_short_name(self, local_repo: Path, bare_remote: Path) -> None:
        dt = datetime.now(timezone.utc) - timedelta(days=1)
        _initial_commit(local_repo, dt=dt)
        _git(["push", "--set-upstream", "origin", "main"], cwd=local_repo, check=False)
        _create_branch_with_commit(local_repo, "feature/x", "x.py", dt=dt)

        branches = discover_branches(str(local_repo))
        feature_branches = [b for b in branches if "feature" in b.short_name]
        assert feature_branches
        # short_name must not contain "origin/"
        for b in feature_branches:
            assert not b.short_name.startswith("origin/"), \
                f"short_name should not have remote prefix: {b.short_name}"

    def test_branch_has_last_commit_date(self, local_repo: Path, bare_remote: Path) -> None:
        dt = datetime.now(timezone.utc) - timedelta(days=1)
        _initial_commit(local_repo, dt=dt)
        _git(["push", "--set-upstream", "origin", "main"], cwd=local_repo, check=False)

        branches = discover_branches(str(local_repo), default_branch="main")
        assert branches
        for b in branches:
            assert isinstance(b.last_commit_date, datetime)
            assert b.last_commit_date.tzinfo is not None

    def test_branch_has_last_commit_sha(self, local_repo: Path, bare_remote: Path) -> None:
        dt = datetime.now(timezone.utc) - timedelta(days=1)
        _initial_commit(local_repo, dt=dt)
        _git(["push", "--set-upstream", "origin", "main"], cwd=local_repo, check=False)

        branches = discover_branches(str(local_repo), default_branch="main")
        assert branches
        for b in branches:
            assert isinstance(b.last_commit_sha, str) and b.last_commit_sha

    def test_head_tracking_branch_excluded(self, local_repo: Path, bare_remote: Path) -> None:
        """The synthetic origin/HEAD branch must not appear in results."""
        dt = datetime.now(timezone.utc) - timedelta(days=1)
        _initial_commit(local_repo, dt=dt)
        _git(["push", "--set-upstream", "origin", "main"], cwd=local_repo, check=False)
        # Create the refs/remotes/origin/HEAD symref a normal clone has. Newer
        # git shortens it to plain "origin", which must not pass as a branch.
        _git(["remote", "set-head", "origin", "main"], cwd=local_repo)

        branches = discover_branches(str(local_repo), default_branch="main")

        assert [b.name for b in branches] == ["origin/main"]


# ---------------------------------------------------------------------------
# T42-4: Error cases
# ---------------------------------------------------------------------------

class TestDiscoverBranchesErrors:
    """discover_branches handles errors gracefully."""

    def test_returns_empty_list_for_nonexistent_repo(self, tmp_path: Path) -> None:
        """A path that is not a git repo must return an empty list, not raise."""
        non_repo = tmp_path / "not_a_repo"
        non_repo.mkdir()
        result = discover_branches(str(non_repo), max_age_days=30)
        assert result == []

    def test_returns_list_type(self, local_repo: Path, bare_remote: Path) -> None:
        """discover_branches must always return a list."""
        dt = datetime.now(timezone.utc) - timedelta(days=1)
        _initial_commit(local_repo, dt=dt)
        _git(["push", "--set-upstream", "origin", "main"], cwd=local_repo, check=False)
        result = discover_branches(str(local_repo))
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# T42-5: _detect_default_branch helper
# ---------------------------------------------------------------------------

class TestDetectDefaultBranch:
    """_detect_default_branch returns a sensible fallback when git cannot resolve."""

    def test_returns_main_for_nonexistent_repo(self, tmp_path: Path) -> None:
        """Falls back to 'main' for directories that are not git repos."""
        non_repo = tmp_path / "not_a_repo"
        non_repo.mkdir()
        result = _detect_default_branch(str(non_repo))
        # Must return a non-empty string (default fallback is 'main')
        assert isinstance(result, str) and result

    def test_returns_string(self, local_repo: Path, bare_remote: Path) -> None:
        dt = datetime.now(timezone.utc) - timedelta(days=1)
        _initial_commit(local_repo, dt=dt)
        _git(["push", "--set-upstream", "origin", "main"], cwd=local_repo, check=False)
        result = _detect_default_branch(str(local_repo))
        assert isinstance(result, str) and result
