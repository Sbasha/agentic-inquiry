"""Tests for onboard staleness detection."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch


from agent_vault.onboard.models import OnboardRun
from agent_vault.onboard.staleness import (
    check_onboard_staleness,
    _count_changed_files,
    _count_commits_since,
)


def _make_run(
    days_ago: int = 0,
    commit_sha: str = "abc123",
    **kwargs: object,
) -> OnboardRun:
    """Helper to create an OnboardRun for tests."""
    return OnboardRun(
        run_id=str(uuid.uuid4()),
        project_id="test-project",
        timestamp=datetime.now(timezone.utc) - timedelta(days=days_ago),
        status="completed",
        is_latest=True,
        commit_sha=commit_sha,
        file_count=100,
        chunk_count=500,
        entity_count=200,
        artifact_path="/tmp/test",
        **kwargs,
    )


class TestStalenessCheck:
    """Tests for check_onboard_staleness."""

    async def test_no_onboard_is_stale(self) -> None:
        mock_service = AsyncMock()
        mock_service.get_latest_onboard.return_value = None

        result = await check_onboard_staleness(
            mock_service, Path("/tmp/workspace")
        )

        assert result.is_stale is True
        assert result.reason == "no_onboard"

    @patch("agent_vault.onboard.staleness._count_changed_files", return_value=0)
    @patch("agent_vault.onboard.staleness._count_commits_since", return_value=0)
    async def test_fresh_onboard_not_stale(
        self, mock_commits: AsyncMock, mock_files: AsyncMock
    ) -> None:
        mock_service = AsyncMock()
        mock_service.get_latest_onboard.return_value = _make_run(days_ago=1)

        result = await check_onboard_staleness(
            mock_service, Path("/tmp/workspace")
        )

        assert result.is_stale is False
        assert result.days_since_onboard == 1

    @patch("agent_vault.onboard.staleness._count_changed_files", return_value=0)
    @patch("agent_vault.onboard.staleness._count_commits_since", return_value=0)
    async def test_old_onboard_is_stale(
        self, mock_commits: AsyncMock, mock_files: AsyncMock
    ) -> None:
        mock_service = AsyncMock()
        mock_service.get_latest_onboard.return_value = _make_run(days_ago=30)

        result = await check_onboard_staleness(
            mock_service, Path("/tmp/workspace")
        )

        assert result.is_stale is True
        assert result.reason == "days_elapsed"

    @patch("agent_vault.onboard.staleness._count_changed_files", return_value=50)
    @patch("agent_vault.onboard.staleness._count_commits_since", return_value=2)
    async def test_many_file_changes_is_stale(
        self, mock_commits: AsyncMock, mock_files: AsyncMock
    ) -> None:
        mock_service = AsyncMock()
        mock_service.get_latest_onboard.return_value = _make_run(days_ago=1)

        result = await check_onboard_staleness(
            mock_service, Path("/tmp/workspace")
        )

        assert result.is_stale is True
        assert result.reason == "file_changes"
        assert result.files_changed == 50

    @patch("agent_vault.onboard.staleness._count_changed_files", return_value=0)
    @patch("agent_vault.onboard.staleness._count_commits_since", return_value=20)
    async def test_many_commits_is_stale(
        self, mock_commits: AsyncMock, mock_files: AsyncMock
    ) -> None:
        mock_service = AsyncMock()
        mock_service.get_latest_onboard.return_value = _make_run(days_ago=1)

        result = await check_onboard_staleness(
            mock_service, Path("/tmp/workspace")
        )

        assert result.is_stale is True
        assert result.reason == "commits"

    @patch("agent_vault.onboard.staleness._count_changed_files", return_value=0)
    @patch("agent_vault.onboard.staleness._count_commits_since", return_value=0)
    async def test_no_commit_sha_skips_git_checks(
        self, mock_commits: AsyncMock, mock_files: AsyncMock
    ) -> None:
        mock_service = AsyncMock()
        mock_service.get_latest_onboard.return_value = _make_run(
            days_ago=1, commit_sha=None
        )

        result = await check_onboard_staleness(
            mock_service, Path("/tmp/workspace")
        )

        assert result.is_stale is False
        mock_files.assert_not_called()
        mock_commits.assert_not_called()

    async def test_message_includes_reason(self) -> None:
        mock_service = AsyncMock()
        mock_service.get_latest_onboard.return_value = None

        result = await check_onboard_staleness(
            mock_service, Path("/tmp/workspace")
        )

        assert "No onboard documentation" in result.message
        assert "/agv:onboard" in result.message


class TestGitHelpers:
    """Tests for git helper functions."""

    async def test_count_changed_files_nonexistent_commit(self) -> None:
        # Should return 0 for invalid commit
        count = await _count_changed_files(
            Path("/tmp"), "nonexistent_commit_sha"
        )
        assert count == 0

    async def test_count_commits_nonexistent_commit(self) -> None:
        count = await _count_commits_since(
            Path("/tmp"), "nonexistent_commit_sha"
        )
        assert count == 0
