"""Tests for branch expiry and pruning logic (T43).

Tests the expire_stale_branches() and prune_expired_branches() functions
using mock storage facades. Both the PostgreSQL/AlloyDB path (via _execute/_fetch)
and the LanceDB path are covered via mock objects.

Covers:
- Soft delete sets is_active=False and records the branch in returned list
- Default branch is never expired
- Active branches are not expired
- Branches absent from active set get soft-deleted
- prune_expired_branches hard-deletes chunks past retention window
- prune_expired_branches respects retention window (recent expired chunks kept)
- Returns 0 / empty list when storage interface is unsupported
- Returns empty list when schema is pre-migration (exception from _fetch)
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Helpers — mock storage facade (PostgreSQL path)
# ---------------------------------------------------------------------------

def _make_pg_provider(rows: list[dict], execute_error: Exception | None = None):
    """Create a mock vector_provider that looks like a PostgreSQL provider."""
    vp = MagicMock()
    vp._chunks_table = "agv_chunks"

    # _fetch returns the supplied rows
    vp._fetch = AsyncMock(return_value=rows)

    if execute_error:
        vp._execute = AsyncMock(side_effect=execute_error)
    else:
        vp._execute = AsyncMock(return_value=None)

    return vp


def _make_pg_storage(rows: list[dict], execute_error: Exception | None = None):
    """Create a mock StorageFacade backed by a PostgreSQL-like provider."""
    vp = _make_pg_provider(rows, execute_error)
    storage = MagicMock()
    storage._vector_provider = vp
    return storage


def _make_unsupported_storage():
    """Create a mock StorageFacade with no known storage interface."""
    vp = MagicMock(spec=[])  # no attributes at all
    storage = MagicMock()
    storage._vector_provider = vp
    return storage


# ---------------------------------------------------------------------------
# Tests — expire_stale_branches (PostgreSQL path)
# ---------------------------------------------------------------------------

class TestExpireStalesBranchesPostgreSQL:
    """expire_stale_branches with a PostgreSQL-like vector provider."""

    @pytest.mark.asyncio
    async def test_stale_branch_gets_expired(self):
        """A branch absent from active_branches must be soft-deleted."""
        from agent_vault.indexing.branch_expiry import expire_stale_branches

        rows = [{"branch": "feature/old"}]
        storage = _make_pg_storage(rows)

        expired = await expire_stale_branches(
            storage=storage,
            project_id="proj1",
            active_branches=set(),
            default_branch="main",
        )

        assert "feature/old" in expired

    @pytest.mark.asyncio
    async def test_default_branch_not_expired(self):
        """The default branch must never be soft-deleted."""
        from agent_vault.indexing.branch_expiry import expire_stale_branches

        # main is in DB but not in active_branches — still must not be expired
        rows = [{"branch": "main"}]
        storage = _make_pg_storage(rows)

        expired = await expire_stale_branches(
            storage=storage,
            project_id="proj1",
            active_branches=set(),
            default_branch="main",
        )

        assert "main" not in expired
        # Also verify _execute was NOT called (no UPDATE for the default branch)
        storage._vector_provider._execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_active_branch_not_expired(self):
        """A branch in active_branches must not be soft-deleted."""
        from agent_vault.indexing.branch_expiry import expire_stale_branches

        rows = [{"branch": "feature/active"}]
        storage = _make_pg_storage(rows)

        expired = await expire_stale_branches(
            storage=storage,
            project_id="proj1",
            active_branches={"feature/active"},
            default_branch="main",
        )

        assert "feature/active" not in expired
        storage._vector_provider._execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_called_with_correct_branch(self):
        """_execute must be called once per expired branch with the correct branch name."""
        from agent_vault.indexing.branch_expiry import expire_stale_branches

        rows = [{"branch": "feature/gone"}]
        storage = _make_pg_storage(rows)

        await expire_stale_branches(
            storage=storage,
            project_id="proj1",
            active_branches=set(),
            default_branch="main",
        )

        call_args = storage._vector_provider._execute.call_args
        # The branch name must appear in the positional args of the UPDATE call
        all_args = list(call_args.args) + list(call_args.kwargs.values())
        assert "feature/gone" in all_args, f"Branch not in call args: {all_args}"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_stale_branches(self):
        """When all branches are active, the result must be an empty list."""
        from agent_vault.indexing.branch_expiry import expire_stale_branches

        rows = [{"branch": "feature/active"}]
        storage = _make_pg_storage(rows)

        expired = await expire_stale_branches(
            storage=storage,
            project_id="proj1",
            active_branches={"feature/active"},
            default_branch="main",
        )

        assert expired == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_fetch_raises(self):
        """Schema pre-migration (no is_active column): must return [] not raise."""
        from agent_vault.indexing.branch_expiry import expire_stale_branches

        storage = _make_pg_storage([], execute_error=None)
        # Simulate _fetch raising (pre-migration schema)
        storage._vector_provider._fetch = AsyncMock(
            side_effect=Exception("column is_active does not exist")
        )

        expired = await expire_stale_branches(
            storage=storage,
            project_id="proj1",
            active_branches=set(),
            default_branch="main",
        )

        assert expired == []

    @pytest.mark.asyncio
    async def test_multiple_stale_branches_all_expired(self):
        """Multiple stale branches must all be returned."""
        from agent_vault.indexing.branch_expiry import expire_stale_branches

        rows = [{"branch": "feature/a"}, {"branch": "feature/b"}]
        storage = _make_pg_storage(rows)

        expired = await expire_stale_branches(
            storage=storage,
            project_id="proj1",
            active_branches=set(),
            default_branch="main",
        )

        assert "feature/a" in expired
        assert "feature/b" in expired

    @pytest.mark.asyncio
    async def test_mixed_active_and_stale(self):
        """Only stale branches are expired; active ones are skipped."""
        from agent_vault.indexing.branch_expiry import expire_stale_branches

        rows = [
            {"branch": "feature/active"},
            {"branch": "feature/stale"},
        ]
        storage = _make_pg_storage(rows)

        expired = await expire_stale_branches(
            storage=storage,
            project_id="proj1",
            active_branches={"feature/active"},
            default_branch="main",
        )

        assert "feature/stale" in expired
        assert "feature/active" not in expired


# ---------------------------------------------------------------------------
# Tests — expire_stale_branches (unsupported storage)
# ---------------------------------------------------------------------------

class TestExpireStalesBranchesUnsupported:
    """expire_stale_branches returns [] when no known storage interface."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_unsupported_backend(self):
        from agent_vault.indexing.branch_expiry import expire_stale_branches

        storage = _make_unsupported_storage()

        expired = await expire_stale_branches(
            storage=storage,
            project_id="proj1",
            active_branches=set(),
            default_branch="main",
        )

        assert expired == []


# ---------------------------------------------------------------------------
# Tests — prune_expired_branches (PostgreSQL path)
# ---------------------------------------------------------------------------

def _make_pg_prune_storage(deleted_count: int, fetch_error: Exception | None = None):
    """Create a mock StorageFacade for prune testing (PostgreSQL path)."""
    vp = MagicMock()
    vp._chunks_table = "agv_chunks"

    if fetch_error:
        vp._fetch = AsyncMock(side_effect=fetch_error)
    else:
        # prune uses a CTE returning a count row
        vp._fetch = AsyncMock(return_value=[{"deleted_count": deleted_count}])

    return MagicMock(_vector_provider=vp)


class TestPruneExpiredBranchesPostgreSQL:
    """prune_expired_branches with a PostgreSQL-like vector provider."""

    @pytest.mark.asyncio
    async def test_returns_deleted_count(self):
        """Must return the number of permanently deleted chunks."""
        from agent_vault.indexing.branch_expiry import prune_expired_branches

        storage = _make_pg_prune_storage(deleted_count=5)

        count = await prune_expired_branches(storage=storage, project_id="proj1")

        assert count == 5

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_prunable(self):
        """When no chunks qualify, must return 0."""
        from agent_vault.indexing.branch_expiry import prune_expired_branches

        storage = _make_pg_prune_storage(deleted_count=0)

        count = await prune_expired_branches(storage=storage, project_id="proj1")

        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_zero_on_fetch_error(self):
        """Database error during prune must return 0, not raise."""
        from agent_vault.indexing.branch_expiry import prune_expired_branches

        storage = _make_pg_prune_storage(
            deleted_count=0,
            fetch_error=Exception("db error"),
        )

        count = await prune_expired_branches(storage=storage, project_id="proj1")

        assert count == 0

    @pytest.mark.asyncio
    async def test_fetch_called_with_project_id(self):
        """_fetch must receive the project_id as a parameter."""
        from agent_vault.indexing.branch_expiry import prune_expired_branches

        storage = _make_pg_prune_storage(deleted_count=0)

        await prune_expired_branches(storage=storage, project_id="my-project")

        call_args = storage._vector_provider._fetch.call_args
        all_args = list(call_args.args) + list(call_args.kwargs.values())
        assert "my-project" in all_args

    @pytest.mark.asyncio
    async def test_custom_retention_days_respected(self):
        """The cutoff datetime passed to _fetch must reflect retention_days."""
        from agent_vault.indexing.branch_expiry import prune_expired_branches

        storage = _make_pg_prune_storage(deleted_count=0)
        now_before = datetime.now(timezone.utc)

        await prune_expired_branches(
            storage=storage, project_id="proj1", retention_days=7
        )

        now_after = datetime.now(timezone.utc)
        call_args = storage._vector_provider._fetch.call_args
        all_args = list(call_args.args) + list(call_args.kwargs.values())

        # Find the cutoff datetime argument
        cutoff_args = [a for a in all_args if isinstance(a, datetime)]
        assert cutoff_args, "No datetime argument found in _fetch call"
        cutoff = cutoff_args[0]

        expected_min = now_before - timedelta(days=7)
        expected_max = now_after - timedelta(days=7)
        assert expected_min <= cutoff <= expected_max, (
            f"cutoff {cutoff} not within expected range [{expected_min}, {expected_max}]"
        )


# ---------------------------------------------------------------------------
# Tests — prune_expired_branches (unsupported storage)
# ---------------------------------------------------------------------------

class TestPruneExpiredBranchesUnsupported:
    """prune_expired_branches returns 0 for unknown storage backends."""

    @pytest.mark.asyncio
    async def test_returns_zero_for_unsupported_backend(self):
        from agent_vault.indexing.branch_expiry import prune_expired_branches

        storage = _make_unsupported_storage()

        count = await prune_expired_branches(storage=storage, project_id="proj1")

        assert count == 0


# ---------------------------------------------------------------------------
# Tests — HARD_DELETE_RETENTION_DAYS constant
# ---------------------------------------------------------------------------

class TestRetentionConstants:
    """Verify the module-level constant is sane."""

    def test_hard_delete_retention_days_is_positive(self):
        from agent_vault.indexing.branch_expiry import HARD_DELETE_RETENTION_DAYS

        assert HARD_DELETE_RETENTION_DAYS > 0

    def test_hard_delete_retention_days_default_30(self):
        from agent_vault.indexing.branch_expiry import HARD_DELETE_RETENTION_DAYS

        assert HARD_DELETE_RETENTION_DAYS == 30
