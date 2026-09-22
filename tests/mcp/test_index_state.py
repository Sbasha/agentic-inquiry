"""Tests for index state detection utilities.

This module tests the index state detection functionality including
the is_indexing_stale() helper function and detect_index_state() integration.
"""

import pytest

pytestmark = pytest.mark.unit

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_vault.mcp.utils.index_state import (
    IndexState,
    IndexStateInfo,
    detect_index_state,
    estimate_indexing_eta,
    is_indexing_stale,
)


class TestIsIndexingStale:
    """Tests for the is_indexing_stale() helper function."""

    def test_stale_when_no_progress_time_and_start_time_old(self) -> None:
        """Should detect stale when no progress and start time is old."""
        now = datetime.now(timezone.utc)
        old_start = now - timedelta(seconds=400)

        result = is_indexing_stale(
            last_progress_time=None,
            start_time=old_start,
            max_stale_seconds=300,
        )

        assert result is True

    def test_not_stale_when_no_progress_time_but_start_time_recent(self) -> None:
        """Should not detect stale when no progress but start time is recent."""
        now = datetime.now(timezone.utc)
        recent_start = now - timedelta(seconds=60)

        result = is_indexing_stale(
            last_progress_time=None,
            start_time=recent_start,
            max_stale_seconds=300,
        )

        assert result is False

    def test_stale_when_progress_time_old(self) -> None:
        """Should detect stale when last progress time is old."""
        now = datetime.now(timezone.utc)
        old_start = now - timedelta(seconds=600)
        old_progress = now - timedelta(seconds=400)

        result = is_indexing_stale(
            last_progress_time=old_progress,
            start_time=old_start,
            max_stale_seconds=300,
        )

        assert result is True

    def test_not_stale_when_progress_time_recent(self) -> None:
        """Should not detect stale when last progress time is recent."""
        now = datetime.now(timezone.utc)
        old_start = now - timedelta(seconds=600)
        recent_progress = now - timedelta(seconds=60)

        result = is_indexing_stale(
            last_progress_time=recent_progress,
            start_time=old_start,
            max_stale_seconds=300,
        )

        assert result is False

    def test_custom_max_stale_seconds(self) -> None:
        """Should respect custom max_stale_seconds parameter."""
        now = datetime.now(timezone.utc)
        progress_time = now - timedelta(seconds=120)
        start_time = now - timedelta(seconds=200)

        # 120 seconds elapsed, threshold is 100 - should be stale
        result_stale = is_indexing_stale(
            last_progress_time=progress_time,
            start_time=start_time,
            max_stale_seconds=100,
        )
        assert result_stale is True

        # 120 seconds elapsed, threshold is 150 - should NOT be stale
        result_not_stale = is_indexing_stale(
            last_progress_time=progress_time,
            start_time=start_time,
            max_stale_seconds=150,
        )
        assert result_not_stale is False

    def test_boundary_exactly_at_threshold(self) -> None:
        """Should not be stale when exactly at threshold (> not >=)."""
        now = datetime.now(timezone.utc)
        # 299 seconds ago (just under 300 threshold)
        progress_time = now - timedelta(seconds=299)
        start_time = now - timedelta(seconds=400)

        result = is_indexing_stale(
            last_progress_time=progress_time,
            start_time=start_time,
            max_stale_seconds=300,
        )

        # Just under threshold should NOT be considered stale
        assert result is False

    def test_just_over_threshold(self) -> None:
        """Should be stale when just over threshold."""
        now = datetime.now(timezone.utc)
        # 301 seconds ago (just over 300)
        progress_time = now - timedelta(seconds=301)
        start_time = now - timedelta(seconds=400)

        result = is_indexing_stale(
            last_progress_time=progress_time,
            start_time=start_time,
            max_stale_seconds=300,
        )

        assert result is True

    def test_naive_datetime_handling(self) -> None:
        """Should handle naive (non-timezone-aware) datetimes."""
        # Create naive datetime by removing timezone info
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        old_progress = now - timedelta(seconds=400)
        start_time = now - timedelta(seconds=600)

        result = is_indexing_stale(
            last_progress_time=old_progress,
            start_time=start_time,
            max_stale_seconds=300,
        )

        assert result is True

    def test_prefers_progress_time_over_start_time(self) -> None:
        """Should use progress time when available, not start time."""
        now = datetime.now(timezone.utc)
        # Very old start time (10 minutes ago)
        old_start = now - timedelta(seconds=600)
        # Recent progress time (1 minute ago)
        recent_progress = now - timedelta(seconds=60)

        result = is_indexing_stale(
            last_progress_time=recent_progress,
            start_time=old_start,
            max_stale_seconds=300,
        )

        # Should use recent progress, not old start - so NOT stale
        assert result is False


class TestEstimateIndexingEta:
    """Tests for the estimate_indexing_eta() function."""

    def test_basic_eta_calculation(self) -> None:
        """Should calculate ETA correctly for normal case."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(seconds=10)

        # 10 files in 10 seconds = 1 file/second
        # 90 files remaining = 90 seconds
        result = estimate_indexing_eta(
            files_processed=10,
            total_files=100,
            start_time=start,
            current_time=now,
        )

        assert result == 90

    def test_returns_none_when_insufficient_elapsed_time(self) -> None:
        """Should return None when less than 5 seconds have elapsed."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(seconds=3)

        result = estimate_indexing_eta(
            files_processed=10,
            total_files=100,
            start_time=start,
            current_time=now,
        )

        assert result is None

    def test_returns_none_when_no_files_processed(self) -> None:
        """Should return None when no files have been processed."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(seconds=10)

        result = estimate_indexing_eta(
            files_processed=0,
            total_files=100,
            start_time=start,
            current_time=now,
        )

        assert result is None

    def test_returns_zero_when_complete(self) -> None:
        """Should return 0 when all files are processed."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(seconds=10)

        result = estimate_indexing_eta(
            files_processed=100,
            total_files=100,
            start_time=start,
            current_time=now,
        )

        assert result == 0


class TestIndexStateInfo:
    """Tests for the IndexStateInfo dataclass."""

    def test_to_dict_excludes_none_values(self) -> None:
        """Should exclude None values from dictionary output."""
        info = IndexStateInfo(
            status=IndexState.READY,
            indexed_so_far=100,
            message="Index is ready.",
        )

        result = info.to_dict()

        assert "status" in result
        assert "indexed_so_far" in result
        assert "message" in result
        assert "progress_percent" not in result
        assert "eta_seconds" not in result
        assert "total_discovered" not in result

    def test_to_dict_includes_all_values_when_set(self) -> None:
        """Should include all values when they are set."""
        info = IndexStateInfo(
            status=IndexState.INDEXING,
            progress_percent=50.123,
            eta_seconds=120,
            indexed_so_far=50,
            total_discovered=100,
            message="Indexing in progress.",
        )

        result = info.to_dict()

        assert result["status"] == "indexing"
        assert result["progress_percent"] == 50.1  # Rounded to 1 decimal
        assert result["eta_seconds"] == 120
        assert result["indexed_so_far"] == 50
        assert result["total_discovered"] == 100
        assert result["message"] == "Indexing in progress."

    def test_stale_status_dict(self) -> None:
        """Should correctly serialize STALE status."""
        info = IndexStateInfo(
            status=IndexState.STALE,
            indexed_so_far=25,
            total_discovered=100,
            message=(
                "Indexing appears stuck (no progress in 5 minutes). "
                "Consider restarting with add_knowledge(force_reindex=true)."
            ),
        )

        result = info.to_dict()

        assert result["status"] == "stale"
        assert "force_reindex" in result["message"]


class MockEvent:
    """Mock event for testing."""

    def __init__(
        self,
        operation_id: str,
        timestamp: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.operation_id = operation_id
        self.timestamp = timestamp
        self.metadata = metadata or {}


class TestDetectIndexStateWithStaleDetection:
    """Integration tests for detect_index_state() stale detection."""

    @pytest.fixture
    def mock_db_manager(self) -> MagicMock:
        """Create a mock database manager."""
        manager = MagicMock()
        manager.count_records = AsyncMock(return_value=100)
        return manager

    @pytest.fixture
    def mock_event_store(self) -> MagicMock:
        """Create a mock event store."""
        store = MagicMock()
        store.get_events_by_type = AsyncMock(return_value=[])
        store.get_operation_status = AsyncMock(return_value={})
        return store

    @pytest.mark.asyncio
    async def test_returns_ready_when_no_active_operations(
        self,
        mock_db_manager: MagicMock,
        mock_event_store: MagicMock,
    ) -> None:
        """Should return READY when no active indexing operations."""
        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        assert result.status == IndexState.READY
        assert result.indexed_so_far == 100

    @pytest.mark.asyncio
    async def test_returns_sparse_when_few_chunks(
        self,
        mock_db_manager: MagicMock,
        mock_event_store: MagicMock,
    ) -> None:
        """Should return SPARSE when chunk count is below threshold."""
        mock_db_manager.count_records = AsyncMock(return_value=10)

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
            sparse_threshold=50,
        )

        assert result.status == IndexState.SPARSE
        assert result.indexed_so_far == 10

    @pytest.mark.asyncio
    async def test_returns_stale_when_operation_stuck(
        self,
        mock_db_manager: MagicMock,
        mock_event_store: MagicMock,
    ) -> None:
        """Should return STALE when indexing operation has no recent progress."""
        now = datetime.now(timezone.utc)
        old_timestamp = now - timedelta(seconds=600)

        # Create a started event
        started_event = MockEvent(
            operation_id="op_123",
            timestamp=old_timestamp.timestamp(),
            metadata={"file_count": 100},
        )

        # Return the started event
        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=lambda event_type, **kwargs: [started_event]
            if event_type == "indexing.started"
            else []
        )

        # Return in-progress status with old end_time
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": old_timestamp.timestamp(),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
            max_stale_seconds=300,
        )

        assert result.status == IndexState.STALE
        assert result.message is not None
        assert "force_reindex=true" in result.message
        assert "5 minutes" in result.message

    @pytest.mark.asyncio
    async def test_returns_indexing_when_progress_recent(
        self,
        mock_db_manager: MagicMock,
        mock_event_store: MagicMock,
    ) -> None:
        """Should return INDEXING when there is recent progress."""
        now = datetime.now(timezone.utc)
        recent_timestamp = now - timedelta(seconds=30)

        # Create a started event
        started_event = MockEvent(
            operation_id="op_123",
            timestamp=recent_timestamp.timestamp(),
            metadata={"file_count": 100},
        )

        # Return the started event
        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=lambda event_type, **kwargs: [started_event]
            if event_type == "indexing.started"
            else []
        )

        # Return in-progress status with recent end_time
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "progress",
                "end_time": recent_timestamp.timestamp(),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
            max_stale_seconds=300,
        )

        assert result.status == IndexState.INDEXING

    @pytest.mark.asyncio
    async def test_stale_message_includes_guidance(
        self,
        mock_db_manager: MagicMock,
        mock_event_store: MagicMock,
    ) -> None:
        """Stale message should include actionable guidance."""
        now = datetime.now(timezone.utc)
        old_timestamp = now - timedelta(seconds=600)

        started_event = MockEvent(
            operation_id="op_123",
            timestamp=old_timestamp.timestamp(),
            metadata={"file_count": 100},
        )

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=lambda event_type, **kwargs: [started_event]
            if event_type == "indexing.started"
            else []
        )

        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": old_timestamp.timestamp(),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
            max_stale_seconds=300,
        )

        # Verify the message contains guidance
        assert result.message is not None
        assert "Indexing appears stuck" in result.message
        assert "no progress in" in result.message
        assert "add_knowledge(force_reindex=true)" in result.message

    @pytest.mark.asyncio
    async def test_custom_max_stale_seconds_respected(
        self,
        mock_db_manager: MagicMock,
        mock_event_store: MagicMock,
    ) -> None:
        """Should respect custom max_stale_seconds parameter."""
        now = datetime.now(timezone.utc)
        # 90 seconds ago
        timestamp_90s = now - timedelta(seconds=90)

        started_event = MockEvent(
            operation_id="op_123",
            timestamp=timestamp_90s.timestamp(),
            metadata={"file_count": 100},
        )

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=lambda event_type, **kwargs: [started_event]
            if event_type == "indexing.started"
            else []
        )

        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": timestamp_90s.timestamp(),
            }
        )

        # With max_stale_seconds=60, should be stale (90 > 60)
        result_stale = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
            max_stale_seconds=60,
        )
        assert result_stale.status == IndexState.STALE

        # With max_stale_seconds=120, should NOT be stale (90 < 120)
        result_not_stale = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
            max_stale_seconds=120,
        )
        assert result_not_stale.status == IndexState.INDEXING
