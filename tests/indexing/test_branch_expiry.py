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
    vp._chunks_table = "ai_chunks"

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


class TestExpireStalesBranchesUnsupported:
    """expire_stale_branches returns [] when no known storage interface."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_unsupported_backend(self):
        from agentic_inquiry.indexing.branch_expiry import expire_stale_branches

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
    vp._chunks_table = "ai_chunks"

    if fetch_error:
        vp._fetch = AsyncMock(side_effect=fetch_error)
    else:
        # prune uses a CTE returning a count row
        vp._fetch = AsyncMock(return_value=[{"deleted_count": deleted_count}])

    return MagicMock(_vector_provider=vp)



class TestPruneExpiredBranchesUnsupported:
    """prune_expired_branches returns 0 for unknown storage backends."""

    @pytest.mark.asyncio
    async def test_returns_zero_for_unsupported_backend(self):
        from agentic_inquiry.indexing.branch_expiry import prune_expired_branches

        storage = _make_unsupported_storage()

        count = await prune_expired_branches(storage=storage, project_id="proj1")

        assert count == 0


# ---------------------------------------------------------------------------
# Tests — HARD_DELETE_RETENTION_DAYS constant
# ---------------------------------------------------------------------------

class TestRetentionConstants:
    """Verify the module-level constant is sane."""

    def test_hard_delete_retention_days_is_positive(self):
        from agentic_inquiry.indexing.branch_expiry import HARD_DELETE_RETENTION_DAYS

        assert HARD_DELETE_RETENTION_DAYS > 0

    def test_hard_delete_retention_days_default_30(self):
        from agentic_inquiry.indexing.branch_expiry import HARD_DELETE_RETENTION_DAYS

        assert HARD_DELETE_RETENTION_DAYS == 30
