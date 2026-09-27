"""Unit tests for index state detection utilities.

Tests the IndexState enum, IndexStateInfo dataclass, estimate_indexing_eta(),
and detect_index_state() functions from agentic_inquiry/mcp/utils/index_state.py.
"""

import pytest

pytestmark = pytest.mark.unit
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from agentic_inquiry.mcp.utils.index_state import (
    IndexState,
    IndexStateInfo,
    estimate_indexing_eta,
    detect_index_state,
    is_indexing_stale,
)


class TestIndexStateInfo:
    """Tests for IndexStateInfo dataclass."""

    def test_to_dict_excludes_none_values(self):
        """to_dict() should not include None fields."""
        info = IndexStateInfo(
            status=IndexState.READY,
            progress_percent=None,
            eta_seconds=None,
            indexed_so_far=0,
            total_discovered=None,
            message=None,
        )
        result = info.to_dict()

        assert "status" in result
        assert result["status"] == "ready"
        assert "progress_percent" not in result
        assert "eta_seconds" not in result
        assert "indexed_so_far" not in result  # 0 is excluded
        assert "total_discovered" not in result
        assert "message" not in result

    def test_to_dict_includes_all_set_values(self):
        """to_dict() should include all non-None fields."""
        info = IndexStateInfo(
            status=IndexState.INDEXING,
            progress_percent=45.678,
            eta_seconds=120,
            indexed_so_far=50,
            total_discovered=100,
            message="Indexing in progress",
        )
        result = info.to_dict()

        assert result["status"] == "indexing"
        assert result["progress_percent"] == 45.7  # Rounded to 1 decimal
        assert result["eta_seconds"] == 120
        assert result["indexed_so_far"] == 50
        assert result["total_discovered"] == 100
        assert result["message"] == "Indexing in progress"

    def test_progress_percent_rounded(self):
        """progress_percent should be rounded to 1 decimal."""
        info = IndexStateInfo(
            status=IndexState.INDEXING,
            progress_percent=33.3333333,
            indexed_so_far=1,
        )
        result = info.to_dict()

        assert result["progress_percent"] == 33.3

    def test_progress_percent_rounds_correctly_to_one_decimal(self):
        """Verify rounding behavior for various values.

        Note: Python uses "banker's rounding" (round half to even), so
        50.55 rounds to 50.5 (nearest even), not 50.6.
        """
        test_cases = [
            (0.04, 0.0),
            (0.06, 0.1),  # 0.06 clearly rounds to 0.1
            (99.94, 99.9),
            (99.96, 100.0),  # 99.96 clearly rounds to 100.0
            (50.56, 50.6),  # Use .56 to avoid banker's rounding edge case
            (50.54, 50.5),  # 50.54 rounds down to 50.5
        ]

        for input_val, expected in test_cases:
            info = IndexStateInfo(
                status=IndexState.INDEXING,
                progress_percent=input_val,
                indexed_so_far=1,
            )
            result = info.to_dict()
            assert result["progress_percent"] == expected, (
                f"Expected {expected} for input {input_val}, got {result['progress_percent']}"
            )

    def test_indexed_so_far_zero_excluded(self):
        """indexed_so_far=0 should be excluded from dict."""
        info = IndexStateInfo(
            status=IndexState.SPARSE,
            indexed_so_far=0,
        )
        result = info.to_dict()

        assert "indexed_so_far" not in result

    def test_indexed_so_far_positive_included(self):
        """indexed_so_far > 0 should be included in dict."""
        info = IndexStateInfo(
            status=IndexState.SPARSE,
            indexed_so_far=10,
        )
        result = info.to_dict()

        assert result["indexed_so_far"] == 10

    def test_empty_message_excluded(self):
        """Empty string message should be excluded from dict."""
        info = IndexStateInfo(
            status=IndexState.READY,
            message="",
        )
        result = info.to_dict()

        assert "message" not in result


class TestEstimateIndexingEta:
    """Tests for estimate_indexing_eta() function."""

    def test_returns_none_when_less_than_5_seconds(self):
        """Should return None with insufficient data (< 5 seconds elapsed)."""
        start = datetime.now(timezone.utc) - timedelta(seconds=3)
        current = datetime.now(timezone.utc)

        result = estimate_indexing_eta(
            files_processed=10,
            total_files=100,
            start_time=start,
            current_time=current,
        )

        assert result is None

    def test_returns_none_when_zero_files_processed(self):
        """Should return None when no files processed."""
        start = datetime.now(timezone.utc) - timedelta(seconds=30)
        current = datetime.now(timezone.utc)

        result = estimate_indexing_eta(
            files_processed=0,
            total_files=100,
            start_time=start,
            current_time=current,
        )

        assert result is None

    def test_returns_none_when_negative_files_processed(self):
        """Should return None when files_processed is negative."""
        start = datetime.now(timezone.utc) - timedelta(seconds=30)
        current = datetime.now(timezone.utc)

        result = estimate_indexing_eta(
            files_processed=-5,
            total_files=100,
            start_time=start,
            current_time=current,
        )

        assert result is None

    def test_calculates_eta_correctly(self):
        """Should calculate ETA based on processing rate."""
        # 10 files in 10 seconds = 1 file/sec
        # 90 files remaining = 90 seconds
        start = datetime.now(timezone.utc) - timedelta(seconds=10)
        current = datetime.now(timezone.utc)

        result = estimate_indexing_eta(
            files_processed=10,
            total_files=100,
            start_time=start,
            current_time=current,
        )

        assert result == 90

    def test_calculates_eta_with_different_rate(self):
        """Should calculate ETA correctly with different processing rates."""
        # 20 files in 10 seconds = 2 files/sec
        # 80 files remaining = 40 seconds
        start = datetime.now(timezone.utc) - timedelta(seconds=10)
        current = datetime.now(timezone.utc)

        result = estimate_indexing_eta(
            files_processed=20,
            total_files=100,
            start_time=start,
            current_time=current,
        )

        assert result == 40

    def test_returns_zero_when_complete(self):
        """Should return 0 when all files processed."""
        start = datetime.now(timezone.utc) - timedelta(seconds=30)
        current = datetime.now(timezone.utc)

        result = estimate_indexing_eta(
            files_processed=100,
            total_files=100,
            start_time=start,
            current_time=current,
        )

        assert result == 0

    def test_returns_zero_when_over_processed(self):
        """Should return 0 when files_processed > total_files."""
        start = datetime.now(timezone.utc) - timedelta(seconds=30)
        current = datetime.now(timezone.utc)

        result = estimate_indexing_eta(
            files_processed=150,
            total_files=100,
            start_time=start,
            current_time=current,
        )

        assert result == 0

    def test_handles_timezone_aware_datetimes(self):
        """Should work with timezone-aware datetimes."""
        start = datetime.now(timezone.utc) - timedelta(seconds=10)
        current = datetime.now(timezone.utc)

        result = estimate_indexing_eta(
            files_processed=10,
            total_files=100,
            start_time=start,
            current_time=current,
        )

        assert result == 90

    def test_handles_naive_datetimes(self):
        """Should work with naive datetimes (assumed UTC)."""
        start = datetime.now() - timedelta(seconds=10)
        current = datetime.now()

        result = estimate_indexing_eta(
            files_processed=10,
            total_files=100,
            start_time=start,
            current_time=current,
        )

        assert result == 90

    def test_uses_current_time_default(self):
        """Should use current time when current_time not provided."""
        start = datetime.now(timezone.utc) - timedelta(seconds=10)

        result = estimate_indexing_eta(
            files_processed=10,
            total_files=100,
            start_time=start,
        )

        # Result should be approximately 90 (may vary slightly due to time elapsed)
        assert result is not None
        assert 88 <= result <= 92

    def test_returns_integer(self):
        """ETA should be an integer value."""
        start = datetime.now(timezone.utc) - timedelta(seconds=7)
        current = datetime.now(timezone.utc)

        result = estimate_indexing_eta(
            files_processed=10,
            total_files=100,
            start_time=start,
            current_time=current,
        )

        assert result is not None
        assert isinstance(result, int)


class TestDetectIndexState:
    """Tests for detect_index_state() async function."""

    @pytest.fixture
    def mock_db_manager(self):
        """Mock LanceDBManager for testing."""
        manager = MagicMock()
        manager.count_records = AsyncMock(return_value=100)
        return manager

    @pytest.fixture
    def mock_event_store(self):
        """Mock EventStore for testing."""
        store = MagicMock()
        store.get_events_by_type = AsyncMock(return_value=[])
        store.get_operation_status = AsyncMock(return_value={})
        return store

    @pytest.mark.asyncio
    async def test_returns_indexing_when_operation_active(
        self, mock_db_manager, mock_event_store
    ):
        """Should return INDEXING when indexing in progress."""
        # Create mock started event
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = datetime.now(timezone.utc).isoformat()
        started_event.metadata = {"file_count": 100, "files_processed": 50}

        mock_event_store.get_events_by_type = AsyncMock(return_value=[started_event])
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": datetime.now(timezone.utc).isoformat(),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        assert result.status == IndexState.INDEXING

    @pytest.mark.asyncio
    async def test_returns_indexing_with_progress_status(
        self, mock_db_manager, mock_event_store
    ):
        """Should return INDEXING when status is 'progress'."""
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = (
            datetime.now(timezone.utc) - timedelta(seconds=10)
        ).isoformat()
        started_event.metadata = {"file_count": 100}

        progress_event = MagicMock()
        progress_event.operation_id = "op_123"
        progress_event.metadata = {"files_processed": 50, "total_files": 100}

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[
                [started_event],  # First call for started events
                [progress_event],  # Second call for progress events
            ]
        )
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "progress",
                "end_time": datetime.now(timezone.utc).isoformat(),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        assert result.status == IndexState.INDEXING
        assert result.progress_percent == 50.0
        assert result.indexed_so_far == 50
        assert result.total_discovered == 100

    @pytest.mark.asyncio
    async def test_returns_sparse_when_below_threshold(
        self, mock_db_manager, mock_event_store
    ):
        """Should return SPARSE when chunk count < threshold."""
        mock_event_store.get_events_by_type = AsyncMock(return_value=[])
        mock_db_manager.count_records = AsyncMock(return_value=25)

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
            sparse_threshold=50,
        )

        assert result.status == IndexState.SPARSE
        assert result.indexed_so_far == 25
        assert "25 chunks" in result.message

    @pytest.mark.asyncio
    async def test_returns_ready_when_above_threshold(
        self, mock_db_manager, mock_event_store
    ):
        """Should return READY when chunk count >= threshold."""
        mock_event_store.get_events_by_type = AsyncMock(return_value=[])
        mock_db_manager.count_records = AsyncMock(return_value=100)

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
            sparse_threshold=50,
        )

        assert result.status == IndexState.READY
        assert result.indexed_so_far == 100
        assert "ready" in result.message.lower()

    @pytest.mark.asyncio
    async def test_returns_ready_when_equal_to_threshold(
        self, mock_db_manager, mock_event_store
    ):
        """Should return READY when chunk count equals threshold."""
        mock_event_store.get_events_by_type = AsyncMock(return_value=[])
        mock_db_manager.count_records = AsyncMock(return_value=50)

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
            sparse_threshold=50,
        )

        assert result.status == IndexState.READY

    @pytest.mark.asyncio
    async def test_returns_stale_when_no_progress(
        self, mock_db_manager, mock_event_store
    ):
        """Should return STALE when no progress > max_stale_seconds."""
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = (
            datetime.now(timezone.utc) - timedelta(seconds=600)
        ).isoformat()
        started_event.metadata = {"file_count": 100, "files_processed": 50}

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[[started_event], []]  # Started events  # No progress events
        )

        # Last event was 400 seconds ago (> 300 second threshold)
        last_event_time = datetime.now(timezone.utc) - timedelta(seconds=400)
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": last_event_time.isoformat(),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
            max_stale_seconds=300,
        )

        assert result.status == IndexState.STALE
        assert "stuck" in result.message.lower()

    @pytest.mark.asyncio
    async def test_not_stale_within_threshold(self, mock_db_manager, mock_event_store):
        """Should return INDEXING when within max_stale_seconds."""
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = (
            datetime.now(timezone.utc) - timedelta(seconds=100)
        ).isoformat()
        started_event.metadata = {"file_count": 100, "files_processed": 50}

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[[started_event], []]
        )

        # Last event was 100 seconds ago (< 300 second threshold)
        last_event_time = datetime.now(timezone.utc) - timedelta(seconds=100)
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": last_event_time.isoformat(),
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
    async def test_skips_events_without_operation_id(
        self, mock_db_manager, mock_event_store
    ):
        """Should skip events that don't have an operation_id."""
        # Event without operation_id
        event_no_op = MagicMock()
        event_no_op.operation_id = None

        mock_event_store.get_events_by_type = AsyncMock(return_value=[event_no_op])
        mock_db_manager.count_records = AsyncMock(return_value=100)

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        # Should fall through to chunk count check and return READY
        assert result.status == IndexState.READY

    @pytest.mark.asyncio
    async def test_handles_completed_operation(self, mock_db_manager, mock_event_store):
        """Should not return INDEXING for completed operations."""
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = datetime.now(timezone.utc).isoformat()
        started_event.metadata = {"file_count": 100}

        mock_event_store.get_events_by_type = AsyncMock(return_value=[started_event])
        mock_event_store.get_operation_status = AsyncMock(
            return_value={"status": "completed"}
        )
        mock_db_manager.count_records = AsyncMock(return_value=100)

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        # Should fall through to chunk count check
        assert result.status == IndexState.READY

    @pytest.mark.asyncio
    async def test_handles_failed_operation(self, mock_db_manager, mock_event_store):
        """Should not return INDEXING for failed operations."""
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = datetime.now(timezone.utc).isoformat()
        started_event.metadata = {"file_count": 100}

        mock_event_store.get_events_by_type = AsyncMock(return_value=[started_event])
        mock_event_store.get_operation_status = AsyncMock(
            return_value={"status": "failed"}
        )
        mock_db_manager.count_records = AsyncMock(return_value=30)

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        # Should fall through to chunk count check
        assert result.status == IndexState.SPARSE

    @pytest.mark.asyncio
    async def test_handles_event_store_exception(
        self, mock_db_manager, mock_event_store
    ):
        """Should fall through to chunk count check on event store error."""
        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=Exception("Database connection error")
        )
        mock_db_manager.count_records = AsyncMock(return_value=100)

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        # Should fall through to chunk count check
        assert result.status == IndexState.READY

    @pytest.mark.asyncio
    async def test_handles_db_manager_exception(
        self, mock_db_manager, mock_event_store
    ):
        """Should return SPARSE with 0 chunks on db_manager error."""
        mock_event_store.get_events_by_type = AsyncMock(return_value=[])
        mock_db_manager.count_records = AsyncMock(
            side_effect=Exception("Table not found")
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        assert result.status == IndexState.SPARSE
        assert result.indexed_so_far == 0

    @pytest.mark.asyncio
    async def test_handles_unix_timestamp_end_time(
        self, mock_db_manager, mock_event_store
    ):
        """Should handle end_time as Unix timestamp."""
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = (
            datetime.now(timezone.utc) - timedelta(seconds=10)
        ).timestamp()
        started_event.metadata = {"file_count": 100, "files_processed": 50}

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[[started_event], []]
        )

        # Return Unix timestamp instead of ISO string
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": datetime.now(timezone.utc).timestamp(),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        assert result.status == IndexState.INDEXING

    @pytest.mark.asyncio
    async def test_handles_datetime_object_end_time(
        self, mock_db_manager, mock_event_store
    ):
        """Should handle end_time as datetime object."""
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = datetime.now(timezone.utc) - timedelta(seconds=10)
        started_event.metadata = {"file_count": 100, "files_processed": 50}

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[[started_event], []]
        )

        # Return datetime object instead of string
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": datetime.now(timezone.utc),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        assert result.status == IndexState.INDEXING

    @pytest.mark.asyncio
    async def test_handles_naive_datetime_end_time(
        self, mock_db_manager, mock_event_store
    ):
        """Should handle end_time as naive datetime (assumed UTC).

        The implementation treats naive datetimes as UTC, so we use
        datetime.utcnow() to get the current UTC time without timezone info.
        """
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = (
            datetime.now(timezone.utc) - timedelta(seconds=10)
        ).isoformat()
        started_event.metadata = {"file_count": 100, "files_processed": 50}

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[[started_event], []]
        )

        # Return naive datetime that represents "now" in UTC
        # Use utcnow() to get UTC time without timezone info (naive but UTC)
        naive_utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": naive_utc_now,  # Naive datetime in UTC
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        assert result.status == IndexState.INDEXING

    @pytest.mark.asyncio
    async def test_calculates_progress_and_eta(self, mock_db_manager, mock_event_store):
        """Should calculate progress_percent and eta_seconds correctly."""
        # Start time 20 seconds ago, 50% complete = 20 seconds remaining
        start_time = datetime.now(timezone.utc) - timedelta(seconds=20)

        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = start_time.isoformat()
        started_event.metadata = {"file_count": 100, "files_processed": 50}

        progress_event = MagicMock()
        progress_event.operation_id = "op_123"
        progress_event.metadata = {"files_processed": 50, "total_files": 100}

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[
                [started_event],
                [progress_event],
            ]
        )
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "progress",
                "end_time": datetime.now(timezone.utc).isoformat(),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        assert result.progress_percent == 50.0
        # 50 files in 20 seconds = 2.5 files/sec, 50 remaining = ~20 seconds
        assert result.eta_seconds is not None
        assert 18 <= result.eta_seconds <= 22  # Allow small variance

    @pytest.mark.asyncio
    async def test_uses_file_count_from_progress_event(
        self, mock_db_manager, mock_event_store
    ):
        """Should prefer file_count from progress event over started event."""
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = (
            datetime.now(timezone.utc) - timedelta(seconds=10)
        ).isoformat()
        started_event.metadata = {"file_count": 100}

        # Progress event has different total_files
        progress_event = MagicMock()
        progress_event.operation_id = "op_123"
        progress_event.metadata = {"files_processed": 75, "total_files": 150}

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[
                [started_event],
                [progress_event],
            ]
        )
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "progress",
                "end_time": datetime.now(timezone.utc).isoformat(),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        assert result.indexed_so_far == 75
        assert result.total_discovered == 150
        assert result.progress_percent == 50.0  # 75/150 = 50%

    @pytest.mark.asyncio
    async def test_message_includes_eta_when_available(
        self, mock_db_manager, mock_event_store
    ):
        """Should include ETA in message when calculable."""
        start_time = datetime.now(timezone.utc) - timedelta(seconds=10)

        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = start_time.isoformat()
        started_event.metadata = {"file_count": 100, "files_processed": 10}

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[[started_event], []]
        )
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": datetime.now(timezone.utc).isoformat(),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        assert result.message is not None
        assert "ETA" in result.message

    @pytest.mark.asyncio
    async def test_default_sparse_threshold(self, mock_db_manager, mock_event_store):
        """Should use default sparse_threshold of 50."""
        mock_event_store.get_events_by_type = AsyncMock(return_value=[])
        mock_db_manager.count_records = AsyncMock(return_value=49)

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
            # sparse_threshold not specified, should default to 50
        )

        assert result.status == IndexState.SPARSE

    @pytest.mark.asyncio
    async def test_default_max_stale_seconds(self, mock_db_manager, mock_event_store):
        """Should use default max_stale_seconds of 300."""
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = (
            datetime.now(timezone.utc) - timedelta(seconds=600)
        ).isoformat()
        started_event.metadata = {"file_count": 100}

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[[started_event], []]
        )

        # 301 seconds since last progress (just over default 300)
        last_event_time = datetime.now(timezone.utc) - timedelta(seconds=301)
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": last_event_time.isoformat(),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
            # max_stale_seconds not specified, should default to 300
        )

        assert result.status == IndexState.STALE


class TestIndexStateEnum:
    """Tests for IndexState enum values."""

    def test_all_states_have_string_values(self):
        """All enum members should have string values."""
        assert IndexState.INDEXING.value == "indexing"
        assert IndexState.SPARSE.value == "sparse"
        assert IndexState.STALE.value == "stale"
        assert IndexState.READY.value == "ready"

    def test_enum_is_string_subclass(self):
        """IndexState should be a subclass of str."""
        assert isinstance(IndexState.READY, str)
        assert IndexState.READY == "ready"


class TestFormatIndexingMessage:
    """Tests for _format_indexing_message() helper function (via detect_index_state)."""

    @pytest.fixture
    def mock_db_manager(self):
        manager = MagicMock()
        manager.count_records = AsyncMock(return_value=100)
        return manager

    @pytest.fixture
    def mock_event_store(self):
        store = MagicMock()
        store.get_events_by_type = AsyncMock(return_value=[])
        store.get_operation_status = AsyncMock(return_value={})
        return store

    @pytest.mark.asyncio
    async def test_message_format_with_total_files(
        self, mock_db_manager, mock_event_store
    ):
        """Message should include files count and percentage."""
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = (
            datetime.now(timezone.utc) - timedelta(seconds=5)
        ).isoformat()
        started_event.metadata = {"file_count": 100, "files_processed": 25}

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[[started_event], []]
        )
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": datetime.now(timezone.utc).isoformat(),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        assert "25/100" in result.message
        assert "25.0%" in result.message

    @pytest.mark.asyncio
    async def test_message_format_without_total_files(
        self, mock_db_manager, mock_event_store
    ):
        """Message should handle missing total_files gracefully."""
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = (
            datetime.now(timezone.utc) - timedelta(seconds=5)
        ).isoformat()
        started_event.metadata = {"files_processed": 25}  # No file_count

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[[started_event], []]
        )
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": datetime.now(timezone.utc).isoformat(),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        # Should have a message but no percentage since no total
        assert result.message is not None
        assert "25 files processed" in result.message or result.total_discovered is None


class TestIsIndexingStale:
    """Tests for is_indexing_stale() function."""

    def test_not_stale_within_threshold(self):
        """Should return False when within max_stale_seconds."""
        now = datetime.now(timezone.utc)
        recent_time = now - timedelta(seconds=100)

        result = is_indexing_stale(
            last_progress_time=recent_time,
            start_time=now - timedelta(seconds=600),
            max_stale_seconds=300,
        )

        assert result is False

    def test_stale_beyond_threshold(self):
        """Should return True when beyond max_stale_seconds."""
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(seconds=400)

        result = is_indexing_stale(
            last_progress_time=old_time,
            start_time=old_time,
            max_stale_seconds=300,
        )

        assert result is True

    def test_uses_start_time_when_no_progress(self):
        """Should use start_time if no last_progress_time."""
        now = datetime.now(timezone.utc)
        old_start = now - timedelta(seconds=400)

        result = is_indexing_stale(
            last_progress_time=None,
            start_time=old_start,
            max_stale_seconds=300,
        )

        assert result is True

    def test_uses_progress_time_over_start_time(self):
        """Should prefer last_progress_time over start_time."""
        now = datetime.now(timezone.utc)
        old_start = now - timedelta(seconds=600)  # Stale if used
        recent_progress = now - timedelta(seconds=100)  # Not stale

        result = is_indexing_stale(
            last_progress_time=recent_progress,
            start_time=old_start,
            max_stale_seconds=300,
        )

        assert result is False

    def test_handles_naive_datetime(self):
        """Should handle naive datetime (assumed UTC)."""
        # Create naive datetime representing "now" in UTC
        naive_utc_recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            seconds=100
        )
        naive_utc_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            seconds=600
        )

        result = is_indexing_stale(
            last_progress_time=naive_utc_recent,
            start_time=naive_utc_start,
            max_stale_seconds=300,
        )

        assert result is False

    def test_boundary_exactly_at_threshold(self):
        """Should return False when just under max_stale_seconds.

        Note: We use 299 seconds instead of exactly 300 to avoid timing issues
        where microseconds elapse between setting up the test and calling the function.
        """
        now = datetime.now(timezone.utc)
        # Just under 300 seconds ago (not > 300)
        boundary_time = now - timedelta(seconds=299)

        result = is_indexing_stale(
            last_progress_time=boundary_time,
            start_time=boundary_time,
            max_stale_seconds=300,
        )

        assert result is False

    def test_just_over_threshold(self):
        """Should return True when just over max_stale_seconds."""
        now = datetime.now(timezone.utc)
        # Just over 300 seconds (> 300)
        over_time = now - timedelta(seconds=301)

        result = is_indexing_stale(
            last_progress_time=over_time,
            start_time=over_time,
            max_stale_seconds=300,
        )

        assert result is True

    def test_custom_threshold(self):
        """Should respect custom max_stale_seconds."""
        now = datetime.now(timezone.utc)
        time_60s_ago = now - timedelta(seconds=60)

        # Should be stale with 30s threshold
        result_stale = is_indexing_stale(
            last_progress_time=time_60s_ago,
            start_time=time_60s_ago,
            max_stale_seconds=30,
        )
        assert result_stale is True

        # Should not be stale with 90s threshold
        result_not_stale = is_indexing_stale(
            last_progress_time=time_60s_ago,
            start_time=time_60s_ago,
            max_stale_seconds=90,
        )
        assert result_not_stale is False


class TestDetectIndexStateEdgeCases:
    """Additional edge case tests for detect_index_state()."""

    @pytest.fixture
    def mock_db_manager(self):
        manager = MagicMock()
        manager.count_records = AsyncMock(return_value=100)
        return manager

    @pytest.fixture
    def mock_event_store(self):
        store = MagicMock()
        store.get_events_by_type = AsyncMock(return_value=[])
        store.get_operation_status = AsyncMock(return_value={})
        return store

    @pytest.mark.asyncio
    async def test_handles_timestamp_as_unix_float_string(
        self, mock_db_manager, mock_event_store
    ):
        """Should handle start_timestamp as string containing Unix timestamp."""
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        # Use a string that is NOT a valid ISO format but IS a valid Unix timestamp
        unix_ts = (datetime.now(timezone.utc) - timedelta(seconds=10)).timestamp()
        started_event.timestamp = str(unix_ts)
        started_event.metadata = {"file_count": 100, "files_processed": 50}

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[[started_event], []]
        )
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": datetime.now(timezone.utc).isoformat(),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        # Should handle parsing and return INDEXING
        assert result.status == IndexState.INDEXING

    @pytest.mark.asyncio
    async def test_handles_end_time_as_unix_float_string(
        self, mock_db_manager, mock_event_store
    ):
        """Should handle end_time as string containing Unix timestamp."""
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = (
            datetime.now(timezone.utc) - timedelta(seconds=10)
        ).isoformat()
        started_event.metadata = {"file_count": 100, "files_processed": 50}

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[[started_event], []]
        )

        # Return end_time as string containing Unix timestamp (not ISO)
        unix_ts = datetime.now(timezone.utc).timestamp()
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": str(unix_ts),  # String version of Unix timestamp
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        assert result.status == IndexState.INDEXING

    @pytest.mark.asyncio
    async def test_handles_z_suffix_iso_format(self, mock_db_manager, mock_event_store):
        """Should handle ISO format with Z suffix."""
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        # Use Z suffix ISO format
        started_event.timestamp = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        started_event.metadata = {"file_count": 100, "files_processed": 50}

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[[started_event], []]
        )
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.%fZ"
                ),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        assert result.status == IndexState.INDEXING

    @pytest.mark.asyncio
    async def test_handles_naive_start_timestamp(
        self, mock_db_manager, mock_event_store
    ):
        """Should handle naive datetime as start_timestamp."""
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        # Naive datetime object (no timezone)
        naive_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            seconds=10
        )
        started_event.timestamp = naive_time
        started_event.metadata = {"file_count": 100, "files_processed": 50}

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[[started_event], []]
        )
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": datetime.now(timezone.utc).isoformat(),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        assert result.status == IndexState.INDEXING

    @pytest.mark.asyncio
    async def test_no_end_time_in_operation_status(
        self, mock_db_manager, mock_event_store
    ):
        """Should handle operation status with no end_time."""
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = (
            datetime.now(timezone.utc) - timedelta(seconds=10)
        ).isoformat()
        started_event.metadata = {"file_count": 100, "files_processed": 50}

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[[started_event], []]
        )
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                # No end_time key
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        # Should still return INDEXING without stale check
        assert result.status == IndexState.INDEXING

    @pytest.mark.asyncio
    async def test_empty_metadata(self, mock_db_manager, mock_event_store):
        """Should handle events with None or empty metadata."""
        started_event = MagicMock()
        started_event.operation_id = "op_123"
        started_event.timestamp = (
            datetime.now(timezone.utc) - timedelta(seconds=10)
        ).isoformat()
        started_event.metadata = None  # None metadata

        mock_event_store.get_events_by_type = AsyncMock(
            side_effect=[[started_event], []]
        )
        mock_event_store.get_operation_status = AsyncMock(
            return_value={
                "status": "started",
                "end_time": datetime.now(timezone.utc).isoformat(),
            }
        )

        result = await detect_index_state(
            db_manager=mock_db_manager,
            event_store=mock_event_store,
            project_id="test_project",
        )

        assert result.status == IndexState.INDEXING
        assert result.total_discovered is None
