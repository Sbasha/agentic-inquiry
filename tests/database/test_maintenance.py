"""Unit tests for LanceDB maintenance functions.

Tests compact_tables(), cleanup_old_versions(), and run_maintenance().
"""
import asyncio
from collections import defaultdict
from datetime import timedelta
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.database.lancedb_manager import _NO_VERSION_CLEANUP, LanceDBManager


class MockFragment:
    """Mock fragment for testing."""
    pass


class MockVersion:
    """Mock version for testing."""
    pass


class MockTable:
    """Mock LanceDB table for maintenance testing."""

    def __init__(
        self,
        fragments: int = 5,
        versions: int = 3,
        compact_error: bool = False,
        cleanup_error: bool = False,
    ):
        self._fragments = [MockFragment() for _ in range(fragments)]
        self._versions = [MockVersion() for _ in range(versions)]
        self._compact_error = compact_error
        self._cleanup_error = cleanup_error
        self._compacted = False
        self._cleaned = False
        self.optimize_windows: List[timedelta] = []

    def list_fragments(self) -> List[MockFragment]:
        # After compaction, reduce fragments
        if self._compacted:
            return self._fragments[:1] if self._fragments else []
        return self._fragments

    def list_versions(self) -> List[MockVersion]:
        # After cleanup, reduce versions
        if self._cleaned:
            return self._versions[:1] if self._versions else []
        return self._versions

    def optimize(
        self, cleanup_older_than: timedelta, delete_unverified: bool = False
    ) -> None:
        # One ``optimize`` call serves both steps; the manager passes its
        # far-future sentinel for the compaction-only pass.
        self.optimize_windows.append(cleanup_older_than)
        if cleanup_older_than == _NO_VERSION_CLEANUP:
            if self._compact_error:
                raise RuntimeError("Compaction failed")
            self._compacted = True
            return
        if self._cleanup_error:
            raise RuntimeError("Cleanup failed")
        self._cleaned = True


@pytest.fixture
def mock_manager():
    """Create a mock LanceDBManager for testing."""
    manager = MagicMock(spec=LanceDBManager)
    manager._tables = {}
    # compact_tables / cleanup_old_versions hold the per-table lock, which
    # must be a real asyncio.Lock, not a MagicMock.
    manager._table_manager = MagicMock()
    manager._table_manager.table_lock = defaultdict(asyncio.Lock).__getitem__

    async def mock_get_table(table_name: str):
        return manager._tables.get(table_name)

    async def mock_run_sync(func):
        return func()

    manager._get_table_async = AsyncMock(side_effect=mock_get_table)
    manager._run_sync = AsyncMock(side_effect=mock_run_sync)

    # Setup compact_tables to call the real implementation
    async def compact_tables_impl(table_names=None):
        return await LanceDBManager.compact_tables(manager, table_names)

    async def cleanup_old_versions_impl(table_names=None, older_than=timedelta(hours=1)):
        return await LanceDBManager.cleanup_old_versions(manager, table_names, older_than)

    manager.compact_tables = compact_tables_impl
    manager.cleanup_old_versions = cleanup_old_versions_impl

    return manager


# ============================================================================
# compact_tables() Tests
# ============================================================================

class TestCompactTables:
    """Tests for LanceDBManager.compact_tables()."""

    @pytest.mark.asyncio
    async def test_compact_single_table_success(self, mock_manager):
        """Test successful compaction of a single table."""
        mock_table = MockTable(fragments=10)
        mock_manager._tables["document_chunks"] = mock_table

        # Call the real method with the mock
        result = await LanceDBManager.compact_tables(mock_manager, ["document_chunks"])

        assert "document_chunks" in result
        assert result["document_chunks"]["status"] == "success"
        assert result["document_chunks"]["fragments_before"] == 10
        assert result["document_chunks"]["fragments_after"] == 1

    @pytest.mark.asyncio
    async def test_compact_nonexistent_table_skipped(self, mock_manager):
        """Test that non-existent tables are skipped."""
        # No tables added to mock
        result = await LanceDBManager.compact_tables(mock_manager, ["nonexistent_table"])

        assert "nonexistent_table" in result
        assert result["nonexistent_table"]["status"] == "skipped"
        assert "does not exist" in result["nonexistent_table"]["reason"]

    @pytest.mark.asyncio
    async def test_compact_table_with_error(self, mock_manager):
        """Test handling of compaction errors."""
        mock_table = MockTable(fragments=5, compact_error=True)
        mock_manager._tables["document_chunks"] = mock_table

        result = await LanceDBManager.compact_tables(mock_manager, ["document_chunks"])

        assert result["document_chunks"]["status"] == "error"
        assert "Compaction failed" in result["document_chunks"]["error"]

    @pytest.mark.asyncio
    async def test_compact_multiple_tables(self, mock_manager):
        """Test compacting multiple tables."""
        mock_manager._tables["document_chunks"] = MockTable(fragments=8)
        mock_manager._tables["graph_entities"] = MockTable(fragments=5)
        mock_manager._tables["graph_relationships"] = MockTable(fragments=3)

        result = await LanceDBManager.compact_tables(
            mock_manager,
            ["document_chunks", "graph_entities", "graph_relationships"]
        )

        assert len(result) == 3
        assert all(r["status"] == "success" for r in result.values())

    @pytest.mark.asyncio
    async def test_compact_mixed_results(self, mock_manager):
        """Test compaction with mixed success/failure/skip."""
        mock_manager._tables["document_chunks"] = MockTable(fragments=5)
        mock_manager._tables["graph_entities"] = MockTable(fragments=3, compact_error=True)
        # graph_relationships not added (will be skipped)

        result = await LanceDBManager.compact_tables(
            mock_manager,
            ["document_chunks", "graph_entities", "graph_relationships"]
        )

        assert result["document_chunks"]["status"] == "success"
        assert result["graph_entities"]["status"] == "error"
        assert result["graph_relationships"]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_compact_empty_table(self, mock_manager):
        """Test compacting a table with no fragments."""
        mock_table = MockTable(fragments=0)
        mock_manager._tables["document_chunks"] = mock_table

        result = await LanceDBManager.compact_tables(mock_manager, ["document_chunks"])

        assert result["document_chunks"]["status"] == "success"
        assert result["document_chunks"]["fragments_before"] == 0
        assert result["document_chunks"]["fragments_after"] == 0


# ============================================================================
# cleanup_old_versions() Tests
# ============================================================================

class TestCleanupOldVersions:
    """Tests for LanceDBManager.cleanup_old_versions()."""

    @pytest.mark.asyncio
    async def test_cleanup_single_table_success(self, mock_manager):
        """Test successful cleanup of a single table."""
        mock_table = MockTable(versions=5)
        mock_manager._tables["document_chunks"] = mock_table

        result = await LanceDBManager.cleanup_old_versions(
            mock_manager,
            ["document_chunks"],
            older_than=timedelta(hours=1)
        )

        assert "document_chunks" in result
        assert result["document_chunks"]["status"] == "success"
        assert result["document_chunks"]["versions_before"] == 5
        assert result["document_chunks"]["versions_after"] == 1

    @pytest.mark.asyncio
    async def test_cleanup_nonexistent_table_skipped(self, mock_manager):
        """Test that non-existent tables are skipped during cleanup."""
        result = await LanceDBManager.cleanup_old_versions(
            mock_manager,
            ["nonexistent_table"],
            older_than=timedelta(hours=1)
        )

        assert "nonexistent_table" in result
        assert result["nonexistent_table"]["status"] == "skipped"
        assert "does not exist" in result["nonexistent_table"]["reason"]

    @pytest.mark.asyncio
    async def test_cleanup_table_with_error(self, mock_manager):
        """Test handling of cleanup errors."""
        mock_table = MockTable(versions=3, cleanup_error=True)
        mock_manager._tables["document_chunks"] = mock_table

        result = await LanceDBManager.cleanup_old_versions(
            mock_manager,
            ["document_chunks"],
            older_than=timedelta(hours=1)
        )

        assert result["document_chunks"]["status"] == "error"
        assert "Cleanup failed" in result["document_chunks"]["error"]

    @pytest.mark.asyncio
    async def test_cleanup_custom_timedelta(self, mock_manager):
        """Test cleanup with custom older_than timedelta."""
        mock_table = MockTable(versions=10)
        mock_manager._tables["document_chunks"] = mock_table

        # Use a longer retention period
        result = await LanceDBManager.cleanup_old_versions(
            mock_manager,
            ["document_chunks"],
            older_than=timedelta(days=7)
        )

        assert result["document_chunks"]["status"] == "success"

    @pytest.mark.asyncio
    async def test_cleanup_multiple_tables(self, mock_manager):
        """Test cleaning up multiple tables."""
        mock_manager._tables["document_chunks"] = MockTable(versions=5)
        mock_manager._tables["graph_entities"] = MockTable(versions=3)

        result = await LanceDBManager.cleanup_old_versions(
            mock_manager,
            ["document_chunks", "graph_entities"],
            older_than=timedelta(hours=2)
        )

        assert len(result) == 2
        assert all(r["status"] == "success" for r in result.values())

    @pytest.mark.asyncio
    async def test_cleanup_mixed_results(self, mock_manager):
        """Test cleanup with mixed success/failure/skip."""
        mock_manager._tables["document_chunks"] = MockTable(versions=5)
        mock_manager._tables["graph_entities"] = MockTable(versions=3, cleanup_error=True)

        result = await LanceDBManager.cleanup_old_versions(
            mock_manager,
            ["document_chunks", "graph_entities", "graph_relationships"],
            older_than=timedelta(hours=1)
        )

        assert result["document_chunks"]["status"] == "success"
        assert result["graph_entities"]["status"] == "error"
        assert result["graph_relationships"]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_cleanup_empty_versions(self, mock_manager):
        """Test cleanup with no versions (edge case)."""
        mock_table = MockTable(versions=0)
        mock_manager._tables["document_chunks"] = mock_table

        result = await LanceDBManager.cleanup_old_versions(
            mock_manager,
            ["document_chunks"],
            older_than=timedelta(hours=1)
        )

        assert result["document_chunks"]["status"] == "success"
        assert result["document_chunks"]["versions_before"] == 0


# ============================================================================
# run_maintenance() Tests
# ============================================================================

class TestRunMaintenance:
    """Tests for LanceDBManager.run_maintenance()."""

    @pytest.mark.asyncio
    async def test_run_maintenance_success(self, mock_manager):
        """Test successful full maintenance run."""
        mock_manager._tables["document_chunks"] = MockTable(fragments=10, versions=5)
        mock_manager._tables["graph_entities"] = MockTable(fragments=8, versions=3)
        mock_manager._tables["graph_relationships"] = MockTable(fragments=5, versions=2)

        result = await LanceDBManager.run_maintenance(
            mock_manager,
            ["document_chunks", "graph_entities", "graph_relationships"],
            cleanup_older_than=timedelta(hours=1)
        )

        assert "compaction" in result
        assert "cleanup" in result
        assert "summary" in result

        # Check summary has correct totals
        # Expected: (10-1) + (8-1) + (5-1) = 20 fragments reduced
        assert result["summary"]["fragments_reduced"] == 20
        # Expected: (5-1) + (3-1) + (2-1) = 7 versions removed
        assert result["summary"]["versions_removed"] == 7
        # Compaction pass prunes nothing; cleanup pass uses the caller's window
        for table in mock_manager._tables.values():
            assert table.optimize_windows == [_NO_VERSION_CLEANUP, timedelta(hours=1)]

    @pytest.mark.asyncio
    async def test_run_maintenance_partial_failure(self, mock_manager):
        """Test maintenance with partial failures."""
        mock_manager._tables["document_chunks"] = MockTable(fragments=5, versions=3)
        mock_manager._tables["graph_entities"] = MockTable(
            fragments=3, versions=2, compact_error=True
        )

        result = await LanceDBManager.run_maintenance(
            mock_manager,
            ["document_chunks", "graph_entities"],
            cleanup_older_than=timedelta(hours=1)
        )

        # Should still have results for both
        assert result["compaction"]["document_chunks"]["status"] == "success"
        assert result["compaction"]["graph_entities"]["status"] == "error"

        # Cleanup should still run
        assert result["cleanup"]["document_chunks"]["status"] == "success"

    @pytest.mark.asyncio
    async def test_run_maintenance_all_tables_missing(self, mock_manager):
        """Test maintenance when all tables are missing."""
        result = await LanceDBManager.run_maintenance(
            mock_manager,
            ["nonexistent1", "nonexistent2"],
            cleanup_older_than=timedelta(hours=1)
        )

        assert all(r["status"] == "skipped" for r in result["compaction"].values())
        assert all(r["status"] == "skipped" for r in result["cleanup"].values())
        assert result["summary"]["fragments_reduced"] == 0
        assert result["summary"]["versions_removed"] == 0

    @pytest.mark.asyncio
    async def test_run_maintenance_custom_timedelta(self, mock_manager):
        """Test maintenance with custom cleanup timedelta."""
        mock_manager._tables["document_chunks"] = MockTable(fragments=5, versions=10)

        result = await LanceDBManager.run_maintenance(
            mock_manager,
            ["document_chunks"],
            cleanup_older_than=timedelta(days=30)
        )

        assert result["compaction"]["document_chunks"]["status"] == "success"
        assert result["cleanup"]["document_chunks"]["status"] == "success"

    @pytest.mark.asyncio
    async def test_run_maintenance_summary_calculation(self, mock_manager):
        """Test that summary correctly aggregates results."""
        # Table 1: 10 -> 1 fragments, 5 -> 1 versions (9 reduced, 4 removed)
        mock_manager._tables["table1"] = MockTable(fragments=10, versions=5)
        # Table 2: 8 -> 1 fragments, 3 -> 1 versions (7 reduced, 2 removed)
        mock_manager._tables["table2"] = MockTable(fragments=8, versions=3)

        result = await LanceDBManager.run_maintenance(
            mock_manager,
            ["table1", "table2"],
            cleanup_older_than=timedelta(hours=1)
        )

        # Expected: (10-1) + (8-1) = 16 fragments reduced
        assert result["summary"]["fragments_reduced"] == 16
        # Expected: (5-1) + (3-1) = 6 versions removed
        assert result["summary"]["versions_removed"] == 6

    @pytest.mark.asyncio
    async def test_run_maintenance_errors_excluded_from_summary(self, mock_manager):
        """Test that errored tables don't contribute to summary."""
        mock_manager._tables["good_table"] = MockTable(fragments=10, versions=5)
        mock_manager._tables["bad_table"] = MockTable(
            fragments=20, versions=10, compact_error=True
        )

        result = await LanceDBManager.run_maintenance(
            mock_manager,
            ["good_table", "bad_table"],
            cleanup_older_than=timedelta(hours=1)
        )

        # Only good_table should contribute
        assert result["summary"]["fragments_reduced"] == 9  # 10 - 1
        # bad_table's cleanup might still succeed even if compact failed
        # so we check the compaction status
        assert result["compaction"]["bad_table"]["status"] == "error"

    @pytest.mark.asyncio
    async def test_run_maintenance_empty_tables(self, mock_manager):
        """Test maintenance on empty tables."""
        mock_manager._tables["empty_table"] = MockTable(fragments=0, versions=0)

        result = await LanceDBManager.run_maintenance(
            mock_manager,
            ["empty_table"],
            cleanup_older_than=timedelta(hours=1)
        )

        assert result["compaction"]["empty_table"]["status"] == "success"
        assert result["cleanup"]["empty_table"]["status"] == "success"
        assert result["summary"]["fragments_reduced"] == 0
        assert result["summary"]["versions_removed"] == 0
