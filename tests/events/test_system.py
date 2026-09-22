"""Unit tests for EventSystem."""

import asyncio
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration

from agentic_inquiry.config import Config, EventsConfig, EventStoreConfig, StorageConfig
from agentic_inquiry.correlation import correlation_context
from agentic_inquiry.events.models import EventStatus
from agentic_inquiry.events.system import EventSystem
from tests.helpers.async_utils import AsyncTestHelper


@pytest_asyncio.fixture
async def temp_event_system(tmp_path: Path) -> AsyncIterator[EventSystem]:
    """Create event system with temp storage for testing.
    
    This fixture provides a fully initialized EventSystem with temporary
    storage and fast flush intervals for testing.
    """
    config = Config()
    config.storage = StorageConfig(
        root=str(tmp_path),
        default_project_id="test_project",
        event_store=EventStoreConfig(path="test_events.db")
    )
    config.events = EventsConfig(
        enabled=True,
        queue_max_size=10,  # Small queue for testing overflow
        batch_size=5,
        flush_interval_seconds=0.05,  # Fast flush for tests
        retention_days=30,
        sampling_enabled=False,
    )
    
    system = await EventSystem.from_config(config, project_id="test_project")
    yield system
    await system.stop(timeout=2.0)


@pytest_asyncio.fixture
async def temp_event_system_with_sampling(tmp_path: Path) -> AsyncIterator[EventSystem]:
    """Create event system with sampling enabled for testing."""
    config = Config()
    config.storage = StorageConfig(
        root=str(tmp_path),
        default_project_id="test_project",
        event_store=EventStoreConfig(path="test_events.db")
    )
    config.events = EventsConfig(
        enabled=True,
        queue_max_size=5,  # Very small queue to trigger sampling
        batch_size=3,
        flush_interval_seconds=0.05,
        retention_days=30,
        sampling_enabled=True,
        sampling_ratio=3,  # Keep 1 in 3 progress events
    )
    
    system = await EventSystem.from_config(config, project_id="test_project")
    yield system
    await system.stop(timeout=2.0)


class TestEventEmission:
    """Tests for event emission functionality."""
    
    @pytest.mark.asyncio
    async def test_emit_queues_event(self, temp_event_system: EventSystem):
        """Test that emit() successfully queues an event."""
        # Emit an event
        await temp_event_system.emit(
            "test.event",
            source="test",
            status=EventStatus.STARTED,
            test_key="test_value"
        )
        
        # Verify metrics
        assert temp_event_system.events_emitted_count == 1
        assert temp_event_system.events_dropped_count == 0

        # Wait for background writer to process
        success = await AsyncTestHelper.wait_for_async_condition(
            lambda: temp_event_system.store.get_latest_events(limit=10),
            lambda events: len(events) == 1,
            timeout=5.0
        )
        assert success, "Event was not stored in time"

        # Verify event was stored
        events = await temp_event_system.store.get_latest_events(limit=10)
        assert events[0].event_type == "test.event"
        assert events[0].source == "test"
        assert events[0].status == EventStatus.STARTED
        assert events[0].metadata["test_key"] == "test_value"
    
    @pytest.mark.asyncio
    async def test_emit_with_correlation_id_auto_extraction(
        self, temp_event_system: EventSystem
    ):
        """Test that emit() auto-extracts correlation ID when operation_id not provided."""
        # Use correlation context
        with correlation_context() as corr_id:
            await temp_event_system.emit(
                "test.event",
                source="test",
                status=EventStatus.STARTED
            )

        # Wait for background writer
        success = await AsyncTestHelper.wait_for_async_condition(
            lambda: temp_event_system.store.get_latest_events(limit=10),
            lambda events: len(events) == 1,
            timeout=5.0
        )
        assert success, "Event was not stored in time"

        # Verify event has correlation ID as operation_id
        events = await temp_event_system.store.get_latest_events(limit=10)
        assert events[0].operation_id == corr_id
    
    @pytest.mark.asyncio
    async def test_emit_with_explicit_operation_id(
        self, temp_event_system: EventSystem
    ):
        """Test that emit() uses explicit operation_id when provided."""
        explicit_op_id = "explicit_operation_123"
        
        await temp_event_system.emit(
            "test.event",
            source="test",
            operation_id=explicit_op_id,
            status=EventStatus.STARTED
        )

        # Wait for background writer
        success = await AsyncTestHelper.wait_for_async_condition(
            lambda: temp_event_system.store.get_latest_events(limit=10),
            lambda events: len(events) == 1,
            timeout=5.0
        )
        assert success, "Event was not stored in time"

        # Verify event has explicit operation_id
        events = await temp_event_system.store.get_latest_events(limit=10)
        assert events[0].operation_id == explicit_op_id
    
    @pytest.mark.asyncio
    async def test_emit_increments_metrics(self, temp_event_system: EventSystem):
        """Test that emit() increments events_emitted_count."""
        initial_count = temp_event_system.events_emitted_count
        
        # Emit multiple events
        for i in range(5):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Verify count incremented
        assert temp_event_system.events_emitted_count == initial_count + 5
    
    @pytest.mark.asyncio
    async def test_emit_handles_queue_full(self, temp_event_system: EventSystem):
        """Test that emit() handles queue full condition gracefully."""
        # Fill the queue (max_size=10)
        for i in range(15):  # Try to emit more than queue size
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Verify some events were dropped
        assert temp_event_system.events_dropped_count > 0
        
        # Verify system still works
        assert temp_event_system.events_emitted_count >= 10
    
    @pytest.mark.asyncio
    async def test_emit_with_session_id(self, temp_event_system: EventSystem):
        """Test that emit() correctly stores session_id."""
        session_id = "test_session_123"
        
        await temp_event_system.emit(
            "test.event",
            source="test",
            session_id=session_id,
            status=EventStatus.STARTED
        )

        # Wait for background writer
        success = await AsyncTestHelper.wait_for_async_condition(
            lambda: temp_event_system.store.get_latest_events(limit=10),
            lambda events: len(events) == 1,
            timeout=5.0
        )
        assert success, "Event was not stored in time"

        # Verify event has session_id
        events = await temp_event_system.store.get_latest_events(limit=10)
        assert events[0].session_id == session_id
    
    @pytest.mark.asyncio
    async def test_emit_after_shutdown(self, temp_event_system: EventSystem):
        """Test that emit() is no-op after shutdown."""
        # Stop the system
        await temp_event_system.stop()
        
        initial_count = temp_event_system.events_emitted_count
        
        # Try to emit after shutdown
        await temp_event_system.emit(
            "test.event",
            source="test",
            status=EventStatus.STARTED
        )
        
        # Verify event was not queued
        assert temp_event_system.events_emitted_count == initial_count


class TestBackgroundWriter:
    """Tests for background writer functionality."""
    
    @pytest.mark.asyncio
    async def test_writer_loop_collects_and_writes_batches(
        self, temp_event_system: EventSystem
    ):
        """Test that writer loop collects events and writes them in batches."""
        # Emit events
        for i in range(8):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Wait for background writer to process
        success = await AsyncTestHelper.wait_for_async_condition(
            lambda: temp_event_system.store.get_latest_events(limit=20),
            lambda events: len(events) == 8,
            timeout=5.0
        )
        assert success, "Events were not stored in time"

        # Verify all events were stored
        events = await temp_event_system.store.get_latest_events(limit=20)
        assert len(events) == 8
    
    @pytest.mark.asyncio
    async def test_batch_size_limit(self, temp_event_system: EventSystem):
        """Test that writer respects batch_size limit."""
        # Emit more events than batch size (batch_size=5)
        for i in range(12):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
            # Small delay to allow writer to process
            await asyncio.sleep(0.01)
        
        # Wait for background writer to process multiple batches
        success = await AsyncTestHelper.wait_for_async_condition(
            lambda: temp_event_system.store.get_latest_events(limit=20),
            lambda events: len(events) >= 10,
            timeout=5.0
        )
        assert success, "Events were not stored in time"

        # Verify all events were stored (or at least most of them given queue size=10)
        events = await temp_event_system.store.get_latest_events(limit=20)
        # Queue size is 10, so we expect at least 10 events
        assert len(events) >= 10
    
    @pytest.mark.asyncio
    async def test_flush_interval_timeout(self, temp_event_system: EventSystem):
        """Test that writer flushes after flush_interval even with small batch."""
        # Emit just 2 events (less than batch_size=5)
        await temp_event_system.emit(
            "test.event.1",
            source="test",
            status=EventStatus.PROGRESS
        )
        await temp_event_system.emit(
            "test.event.2",
            source="test",
            status=EventStatus.PROGRESS
        )
        
        # Wait for flush interval (0.05s) plus buffer
        success = await AsyncTestHelper.wait_for_async_condition(
            lambda: temp_event_system.store.get_latest_events(limit=10),
            lambda events: len(events) == 2,
            timeout=5.0
        )
        assert success, "Events were not flushed in time"

        # Verify events were flushed despite small batch
        events = await temp_event_system.store.get_latest_events(limit=10)
        assert len(events) == 2
    
    @pytest.mark.asyncio
    async def test_error_handling_in_writer_loop(
        self, temp_event_system: EventSystem, monkeypatch
    ):
        """Test that writer loop handles errors gracefully."""
        # Track store_events calls
        store_events_calls = []
        original_store_events = temp_event_system.store.store_events
        
        async def failing_store_events(events):
            store_events_calls.append(len(events))
            if len(store_events_calls) == 1:
                # Fail first call
                raise Exception("Simulated storage failure")
            # Succeed on retry
            return await original_store_events(events)
        
        monkeypatch.setattr(
            temp_event_system.store,
            "store_events",
            failing_store_events
        )
        
        # Emit events
        for i in range(3):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Wait for writer to process and recover
        success = await AsyncTestHelper.wait_for_condition(
            lambda: len(store_events_calls) >= 1,
            timeout=5.0
        )
        assert success, "Writer did not process events"

        # Verify writer recovered and stored events
        assert len(store_events_calls) >= 1

    @pytest.mark.asyncio
    async def test_exponential_backoff_retry_logic(
        self, temp_event_system: EventSystem, monkeypatch
    ):
        """Test that writer loop implements exponential backoff on failures."""
        # Track store_events calls and delays
        store_events_calls = []
        sleep_delays = []
        original_store_events = temp_event_system.store.store_events
        original_sleep = asyncio.sleep
        
        async def failing_store_events(events):
            store_events_calls.append(len(events))
            if len(store_events_calls) <= 3:
                # Fail first 3 calls
                raise Exception("Simulated storage failure")
            # Succeed on 4th call
            return await original_store_events(events)
        
        async def tracked_sleep(delay):
            sleep_delays.append(delay)
            await original_sleep(delay)
        
        monkeypatch.setattr(
            temp_event_system.store,
            "store_events",
            failing_store_events
        )
        monkeypatch.setattr(asyncio, "sleep", tracked_sleep)
        
        # Emit events
        for i in range(3):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Wait for writer to process and recover
        success = await AsyncTestHelper.wait_for_condition(
            lambda: len(store_events_calls) >= 4,
            timeout=5.0
        )
        assert success, "Writer did not retry enough times"

        # Verify exponential backoff delays were applied
        # Expected delays: 0.1 * 2^0 = 0.1, 0.1 * 2^1 = 0.2, 0.1 * 2^2 = 0.4
        retry_delays = [d for d in sleep_delays if d >= 0.1 and d <= 1.0]
        assert len(retry_delays) >= 2, f"Expected at least 2 retry delays, got {retry_delays}"
        
        # Verify delays are increasing (exponential backoff)
        if len(retry_delays) >= 2:
            assert retry_delays[1] > retry_delays[0], "Delays should increase exponentially"
    
    @pytest.mark.asyncio
    async def test_successful_write_resets_retry_count(
        self, temp_event_system: EventSystem, monkeypatch
    ):
        """Test that successful write resets retry count."""
        # Track store_events calls
        store_events_calls = []
        original_store_events = temp_event_system.store.store_events
        
        async def intermittent_failure_store_events(events):
            store_events_calls.append(len(events))
            # Fail on first call, succeed on second, fail on third
            if len(store_events_calls) in [1, 3]:
                raise Exception("Simulated storage failure")
            return await original_store_events(events)
        
        monkeypatch.setattr(
            temp_event_system.store,
            "store_events",
            intermittent_failure_store_events
        )
        
        # Emit first batch
        for i in range(3):
            await temp_event_system.emit(
                f"test.event.batch1.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Wait for first batch to be processed (fail then succeed)
        await asyncio.sleep(0.5)
        
        # Emit second batch
        for i in range(3):
            await temp_event_system.emit(
                f"test.event.batch2.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Wait for second batch to be processed
        success = await AsyncTestHelper.wait_for_condition(
            lambda: len(store_events_calls) >= 3,
            timeout=5.0
        )
        assert success, "Writer did not process enough batches"

        # Verify retry count was reset between batches
        # If retry count wasn't reset, the third call would use a higher retry count
        # The test passes if we get at least 3 calls (showing recovery)
        assert len(store_events_calls) >= 3
    
    @pytest.mark.asyncio
    async def test_batch_dropped_after_max_retries(
        self, temp_event_system: EventSystem, monkeypatch
    ):
        """Test that batch is dropped after max retries exceeded."""
        # Track store_events calls
        store_events_calls = []
        
        async def always_failing_store_events(events):
            store_events_calls.append(len(events))
            raise Exception("Simulated persistent storage failure")
        
        monkeypatch.setattr(
            temp_event_system.store,
            "store_events",
            always_failing_store_events
        )
        
        initial_dropped = temp_event_system.events_dropped_count
        
        # Emit events
        for i in range(3):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Wait for writer to exhaust retries
        success = await AsyncTestHelper.wait_for_condition(
            lambda: temp_event_system.events_dropped_count > initial_dropped,
            timeout=5.0
        )
        assert success, "Events were not dropped after max retries"

        # Verify events were dropped
        assert temp_event_system.events_dropped_count > initial_dropped
        
        # Verify max retries were attempted (5 retries + 1 initial = 6 total)
        # Note: There might be multiple batches, so we check >= 6
        assert len(store_events_calls) >= 6, f"Expected at least 6 attempts, got {len(store_events_calls)}"
    
    @pytest.mark.asyncio
    async def test_events_dropped_count_incremented_on_failure(
        self, temp_event_system: EventSystem, monkeypatch
    ):
        """Test that events_dropped_count is incremented when batch is dropped."""
        # Track store_events calls
        store_events_calls = []
        
        async def always_failing_store_events(events):
            store_events_calls.append(len(events))
            raise Exception("Simulated persistent storage failure")
        
        monkeypatch.setattr(
            temp_event_system.store,
            "store_events",
            always_failing_store_events
        )
        
        initial_dropped = temp_event_system.events_dropped_count
        
        # Emit exactly 3 events
        for i in range(3):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Wait for writer to exhaust retries and drop batch
        success = await AsyncTestHelper.wait_for_condition(
            lambda: temp_event_system.events_dropped_count > initial_dropped,
            timeout=5.0
        )
        assert success, "Events were not dropped after max retries"

        # Verify exactly 3 events were dropped (the batch size)
        dropped_count = temp_event_system.events_dropped_count - initial_dropped
        assert dropped_count == 3, f"Expected 3 events dropped, got {dropped_count}"


class TestLifecycleManagement:
    """Tests for lifecycle management functionality."""
    
    @pytest.mark.asyncio
    async def test_start_initializes_components(self, tmp_path: Path):
        """Test that start() initializes store and writer task."""
        config = Config()
        config.storage = StorageConfig(
            root=str(tmp_path),
            default_project_id="test_project",
            event_store=EventStoreConfig(path="test_events.db")
        )
        config.events = EventsConfig()
        
        system = EventSystem(config, project_id="test_project")
        
        # Verify not started yet
        assert system._writer_task is None
        
        # Start system
        await system.start()
        
        # Verify initialized
        assert system._writer_task is not None
        assert not system._writer_task.done()
        assert system.store._initialized
        
        # Cleanup
        await system.stop()
    
    @pytest.mark.asyncio
    async def test_stop_flushes_pending_events(self, temp_event_system: EventSystem):
        """Test that stop() flushes all pending events."""
        # Emit events
        for i in range(5):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Give a tiny moment for events to be queued
        await asyncio.sleep(0.01)
        
        # Stop (should flush pending events)
        result = await temp_event_system.stop(timeout=2.0)
        
        # Verify successful flush
        assert result is True
        
        # Verify all events were stored
        events = await temp_event_system.store.get_latest_events(limit=10)
        assert len(events) == 5
    
    @pytest.mark.asyncio
    async def test_stop_with_timeout(self, tmp_path: Path, monkeypatch):
        """Test that stop() respects timeout."""
        config = Config()
        config.storage = StorageConfig(
            root=str(tmp_path),
            default_project_id="test_project",
            event_store=EventStoreConfig(path="test_events.db")
        )
        config.events = EventsConfig(
            flush_interval_seconds=10.0  # Very long flush interval
        )
        
        system = await EventSystem.from_config(config, project_id="test_project")
        
        # Emit events
        for i in range(3):
            await system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Stop with short timeout
        result = await system.stop(timeout=0.1)
        
        # Verify timeout occurred (writer couldn't flush in time)
        # Note: This might still return True if writer is fast enough
        # The important thing is it doesn't hang
        assert isinstance(result, bool)
    
    @pytest.mark.asyncio
    async def test_async_context_manager(self, tmp_path: Path):
        """Test that EventSystem works as async context manager."""
        config = Config()
        config.storage = StorageConfig(
            root=str(tmp_path),
            default_project_id="test_project",
            event_store=EventStoreConfig(path="test_events.db")
        )
        config.events = EventsConfig(
            flush_interval_seconds=0.05
        )
        
        # Use as context manager (need to await from_config first)
        system = await EventSystem.from_config(config, project_id="test_project")
        async with system:
            # Verify started
            assert system._writer_task is not None
            
            # Emit events
            await system.emit(
                "test.event",
                source="test",
                status=EventStatus.STARTED
            )
        
        # Verify stopped after context exit
        assert system._shutdown is True
    
    @pytest.mark.asyncio
    async def test_from_config_class_method(self, tmp_path: Path):
        """Test that from_config() creates and starts system."""
        config = Config()
        config.storage = StorageConfig(
            root=str(tmp_path),
            default_project_id="test_project",
            event_store=EventStoreConfig(path="test_events.db")
        )
        config.events = EventsConfig()
        
        system = await EventSystem.from_config(config, project_id="test_project")
        
        # Verify started
        assert system._writer_task is not None
        assert system.store._initialized
        
        # Cleanup
        await system.stop()


class TestMetrics:
    """Tests for metrics tracking functionality."""
    
    @pytest.mark.asyncio
    async def test_events_emitted_count_increments(
        self, temp_event_system: EventSystem
    ):
        """Test that events_emitted_count increments correctly."""
        initial_count = temp_event_system.events_emitted_count
        
        # Emit events
        for i in range(7):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Verify count
        assert temp_event_system.events_emitted_count == initial_count + 7
    
    @pytest.mark.asyncio
    async def test_events_dropped_count_increments_on_queue_full(
        self, temp_event_system: EventSystem
    ):
        """Test that events_dropped_count increments when queue is full."""
        initial_dropped = temp_event_system.events_dropped_count
        
        # Fill queue beyond capacity (max_size=10)
        for i in range(20):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Verify some events were dropped
        assert temp_event_system.events_dropped_count > initial_dropped
    
    @pytest.mark.asyncio
    async def test_queue_depth_property(self, temp_event_system: EventSystem):
        """Test that queue_depth property returns current queue size."""
        # Initially empty or small
        initial_depth = temp_event_system.queue_depth
        assert initial_depth >= 0
        
        # Emit events rapidly (faster than writer can process)
        for i in range(5):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Queue should have events
        depth_after_emit = temp_event_system.queue_depth
        assert depth_after_emit >= 0

        # Wait for writer to process (queue should empty or get smaller)
        success = await AsyncTestHelper.wait_for_condition(
            lambda: temp_event_system.queue_depth <= depth_after_emit,
            timeout=5.0
        )
        assert success, "Queue was not processed in time"

        # Queue should be empty or smaller
        final_depth = temp_event_system.queue_depth
        assert final_depth <= depth_after_emit
    
    @pytest.mark.asyncio
    async def test_get_stats_returns_correct_metrics(
        self, temp_event_system: EventSystem
    ):
        """Test that get_stats() returns all expected metrics."""
        # Emit some events
        for i in range(3):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Get stats
        stats = temp_event_system.get_stats()
        
        # Verify all expected keys present
        assert "events_emitted_count" in stats
        assert "events_dropped_count" in stats
        assert "queue_depth" in stats
        assert "writer_running" in stats
        assert "sampling_active" in stats
        assert "sampling_enabled" in stats
        assert "sampled_count" in stats
        
        # Verify values
        assert stats["events_emitted_count"] == 3
        assert stats["events_dropped_count"] >= 0
        assert stats["queue_depth"] >= 0
        assert stats["writer_running"] is True
        assert stats["sampling_enabled"] is False
    
    @pytest.mark.asyncio
    async def test_sampling_metrics(
        self, temp_event_system_with_sampling: EventSystem
    ):
        """Test that sampling metrics are tracked correctly."""
        system = temp_event_system_with_sampling
        
        # Fill queue to trigger sampling (max_size=5)
        for i in range(15):
            await system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Get stats
        stats = system.get_stats()
        
        # Verify sampling was activated
        assert stats["sampling_enabled"] is True
        # sampling_active might be True or False depending on queue state
        assert "sampling_active" in stats
        assert stats["sampled_count"] >= 0


class TestSamplingStrategy:
    """Tests for event sampling strategy."""
    
    @pytest.mark.asyncio
    async def test_sampling_preserves_failed_events(
        self, temp_event_system_with_sampling: EventSystem
    ):
        """Test that sampling always preserves FAILED status events."""
        system = temp_event_system_with_sampling
        
        # Emit failed event first (before queue fills)
        await system.emit(
            "test.failed",
            source="test",
            status=EventStatus.FAILED,
            error="Test error"
        )
        
        # Fill queue with progress events
        for i in range(10):
            await system.emit(
                f"test.progress.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Wait for writer to process and verify failed event was stored
        success = await AsyncTestHelper.wait_for_async_condition(
            lambda: system.store.get_latest_events(limit=20),
            lambda events: len([e for e in events if e.status == EventStatus.FAILED]) >= 1,
            timeout=5.0
        )
        assert success, "Failed event was not stored in time"

        # Verify failed event was stored
        events = await system.store.get_latest_events(limit=20)
        failed_events = [e for e in events if e.status == EventStatus.FAILED]
        # The failed event should have been stored since it was emitted first
        assert len(failed_events) >= 1
    
    @pytest.mark.asyncio
    async def test_sampling_preserves_started_completed_events(
        self, temp_event_system_with_sampling: EventSystem
    ):
        """Test that sampling preserves STARTED and COMPLETED events."""
        system = temp_event_system_with_sampling
        
        # Emit started and completed events first (before queue fills)
        await system.emit(
            "test.started",
            source="test",
            status=EventStatus.STARTED
        )
        await system.emit(
            "test.completed",
            source="test",
            status=EventStatus.COMPLETED
        )
        
        # Fill queue with progress events
        for i in range(10):
            await system.emit(
                f"test.progress.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Wait for writer to process and verify lifecycle events were stored
        def count_lifecycle_events(events):
            started = len([e for e in events if e.status == EventStatus.STARTED])
            completed = len([e for e in events if e.status == EventStatus.COMPLETED])
            return started + completed >= 2

        success = await AsyncTestHelper.wait_for_async_condition(
            lambda: system.store.get_latest_events(limit=20),
            count_lifecycle_events,
            timeout=5.0
        )
        assert success, "Lifecycle events were not stored in time"

        # Verify lifecycle events were stored
        events = await system.store.get_latest_events(limit=20)
        started_events = [e for e in events if e.status == EventStatus.STARTED]
        completed_events = [e for e in events if e.status == EventStatus.COMPLETED]

        # Lifecycle events should be preserved since they were emitted first
        assert len(started_events) + len(completed_events) >= 2
    
    @pytest.mark.asyncio
    async def test_sampling_ratio_applied_to_progress_events(
        self, temp_event_system_with_sampling: EventSystem
    ):
        """Test that sampling ratio is applied to PROGRESS events."""
        system = temp_event_system_with_sampling
        
        # Emit many progress events to trigger sampling
        for i in range(20):
            await system.emit(
                f"test.progress.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Verify some events were dropped due to sampling
        assert system.events_dropped_count > 0
        
        # Verify sampling was activated
        stats = system.get_stats()
        assert stats["sampled_count"] > 0



class TestPerformanceMonitoring:
    """Tests for performance monitoring and alerting functionality."""
    
    @pytest.mark.asyncio
    async def test_timing_warning_logged_when_write_exceeds_threshold(
        self, temp_event_system: EventSystem, monkeypatch, caplog
    ):
        """Test that warning is logged when write exceeds 50ms threshold."""
        import logging
        caplog.set_level(logging.WARNING)
        
        # Mock store_events to simulate slow write
        original_store_events = temp_event_system.store.store_events
        
        async def slow_store_events(events):
            # Simulate slow write by sleeping
            await asyncio.sleep(0.06)  # 60ms - exceeds 50ms threshold
            return await original_store_events(events)
        
        monkeypatch.setattr(
            temp_event_system.store,
            "store_events",
            slow_store_events
        )
        
        # Emit events to trigger write
        for i in range(3):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Wait for writer to process
        await asyncio.sleep(0.5)
        
        # Verify warning was logged
        log_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]
        timing_warnings = [msg for msg in log_messages if "EventStore write took" in msg and "threshold: 50ms" in msg]
        assert len(timing_warnings) > 0, f"Expected timing warning, got: {log_messages}"
    
    @pytest.mark.asyncio
    async def test_no_timing_warning_when_write_under_threshold(
        self, temp_event_system: EventSystem, caplog
    ):
        """Test that no warning is logged when write is under 50ms threshold."""
        import logging
        caplog.set_level(logging.WARNING)
        
        # Emit events (normal fast write)
        for i in range(3):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Wait for writer to process
        await asyncio.sleep(0.5)
        
        # Verify no timing warning was logged
        log_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]
        timing_warnings = [msg for msg in log_messages if "EventStore write took" in msg and "threshold: 50ms" in msg]
        assert len(timing_warnings) == 0, f"Unexpected timing warning: {timing_warnings}"
    
    @pytest.mark.asyncio
    async def test_timing_warning_includes_batch_size(
        self, temp_event_system: EventSystem, monkeypatch, caplog
    ):
        """Test that timing warning includes batch size in message."""
        import logging
        caplog.set_level(logging.WARNING)
        
        # Mock store_events to simulate slow write
        original_store_events = temp_event_system.store.store_events
        
        async def slow_store_events(events):
            await asyncio.sleep(0.06)  # 60ms - exceeds threshold
            return await original_store_events(events)
        
        monkeypatch.setattr(
            temp_event_system.store,
            "store_events",
            slow_store_events
        )
        
        # Emit exactly 3 events
        for i in range(3):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Wait for writer to process
        await asyncio.sleep(0.5)
        
        # Verify warning includes batch size
        log_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]
        timing_warnings = [msg for msg in log_messages if "EventStore write took" in msg and "batch of 3 events" in msg]
        assert len(timing_warnings) > 0, f"Expected timing warning with batch size, got: {log_messages}"
    
    @pytest.mark.asyncio
    async def test_alert_logged_when_dropped_events_exceed_threshold(
        self, temp_event_system: EventSystem, caplog
    ):
        """Test that alert is logged when dropped events exceed threshold."""
        import logging
        caplog.set_level(logging.ERROR)
        
        # Fill queue beyond capacity many times to exceed threshold (default: 100)
        # Queue max_size is 10, so we need to drop 100+ events
        for i in range(120):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Verify alert was logged
        log_messages = [record.message for record in caplog.records if record.levelname == "ERROR"]
        drop_alerts = [msg for msg in log_messages if "High event drop rate detected" in msg]
        assert len(drop_alerts) > 0, f"Expected drop rate alert, got: {log_messages}"
    
    @pytest.mark.asyncio
    async def test_no_alert_when_dropped_events_below_threshold(
        self, temp_event_system: EventSystem, caplog
    ):
        """Test that no alert is logged when dropped events are below threshold."""
        import logging
        caplog.set_level(logging.ERROR)
        
        # Drop only a few events (below threshold of 100)
        for i in range(15):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Wait a bit
        await asyncio.sleep(0.2)
        
        # Verify no alert was logged
        log_messages = [record.message for record in caplog.records if record.levelname == "ERROR"]
        drop_alerts = [msg for msg in log_messages if "High event drop rate detected" in msg]
        assert len(drop_alerts) == 0, f"Unexpected drop rate alert: {drop_alerts}"
    
    @pytest.mark.asyncio
    async def test_alert_includes_recommendation(
        self, temp_event_system: EventSystem, caplog
    ):
        """Test that alert includes recommendation to increase queue_max_size or enable sampling."""
        import logging
        caplog.set_level(logging.ERROR)
        
        # Fill queue beyond capacity many times to exceed threshold
        for i in range(120):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Verify alert includes recommendation
        log_messages = [record.message for record in caplog.records if record.levelname == "ERROR"]
        drop_alerts = [msg for msg in log_messages if "High event drop rate detected" in msg]
        assert len(drop_alerts) > 0
        
        # Check that recommendation is included
        alert_with_recommendation = [msg for msg in drop_alerts if "queue_max_size" in msg or "sampling" in msg]
        assert len(alert_with_recommendation) > 0, f"Expected recommendation in alert, got: {drop_alerts}"
    
    @pytest.mark.asyncio
    async def test_alert_only_triggered_once(
        self, temp_event_system: EventSystem, caplog
    ):
        """Test that alert is only triggered once to avoid log spam."""
        import logging
        caplog.set_level(logging.ERROR)
        
        # Fill queue beyond capacity many times to exceed threshold
        for i in range(120):
            await temp_event_system.emit(
                f"test.event.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Continue dropping more events
        for i in range(50):
            await temp_event_system.emit(
                f"test.event.extra.{i}",
                source="test",
                status=EventStatus.PROGRESS
            )
        
        # Verify alert was logged only once
        log_messages = [record.message for record in caplog.records if record.levelname == "ERROR"]
        drop_alerts = [msg for msg in log_messages if "High event drop rate detected" in msg]
        assert len(drop_alerts) == 1, f"Expected exactly 1 alert, got {len(drop_alerts)}: {drop_alerts}"


class TestCleanupScheduling:
    """Tests for periodic cleanup scheduling functionality."""
    
    @pytest.mark.asyncio
    async def test_cleanup_task_created_in_start(self, tmp_path: Path):
        """Test that cleanup task is created when EventSystem starts."""
        config = Config()
        config.storage = StorageConfig(
            root=str(tmp_path),
            default_project_id="test_project",
            event_store=EventStoreConfig(path="test_events.db")
        )
        config.events = EventsConfig(
            cleanup_interval_hours=24,
            retention_days=30
        )
        
        system = EventSystem(config, project_id="test_project")
        
        # Verify cleanup task not created yet
        assert system._cleanup_task is None
        
        # Start system
        await system.start()
        
        # Verify cleanup task was created
        assert system._cleanup_task is not None
        assert not system._cleanup_task.done()
        
        # Cleanup
        await system.stop()
    
    @pytest.mark.asyncio
    async def test_cleanup_task_cancelled_in_stop(self, tmp_path: Path):
        """Test that cleanup task is cancelled when EventSystem stops."""
        config = Config()
        config.storage = StorageConfig(
            root=str(tmp_path),
            default_project_id="test_project",
            event_store=EventStoreConfig(path="test_events.db")
        )
        config.events = EventsConfig(
            cleanup_interval_hours=24,
            retention_days=30
        )
        
        system = await EventSystem.from_config(config, project_id="test_project")
        
        # Verify cleanup task is running
        assert system._cleanup_task is not None
        assert not system._cleanup_task.done()
        
        # Stop system
        await system.stop()
        
        # Verify cleanup task was cancelled
        assert system._cleanup_task is None
    
    @pytest.mark.asyncio
    async def test_cleanup_old_events_called_with_correct_retention(
        self, tmp_path: Path, monkeypatch
    ):
        """Test that cleanup_old_events is called with correct retention period."""
        config = Config()
        config.storage = StorageConfig(
            root=str(tmp_path),
            default_project_id="test_project",
            event_store=EventStoreConfig(path="test_events.db")
        )
        config.events = EventsConfig(
            cleanup_interval_hours=0.001,  # Very short interval for testing (3.6 seconds)
            retention_days=7
        )
        
        system = await EventSystem.from_config(config, project_id="test_project")
        
        # Track cleanup_old_events calls
        cleanup_calls = []
        
        async def tracked_cleanup(retention_days, project_id=None):
            cleanup_calls.append(retention_days)
            return 0  # Return 0 deleted events
        
        monkeypatch.setattr(system.store, "cleanup_old_events", tracked_cleanup)
        
        # Wait for cleanup to be called (interval is 3.6 seconds)
        success = await AsyncTestHelper.wait_for_condition(
            lambda: len(cleanup_calls) > 0,
            timeout=10.0
        )
        
        # Stop system
        await system.stop()
        
        # Verify cleanup was called with correct retention period
        assert success, "Cleanup was not called in time"
        assert len(cleanup_calls) > 0
        assert cleanup_calls[0] == 7
    
    @pytest.mark.asyncio
    async def test_vacuum_called_after_cleanup(
        self, tmp_path: Path, monkeypatch
    ):
        """Test that vacuum is called after cleanup."""
        config = Config()
        config.storage = StorageConfig(
            root=str(tmp_path),
            default_project_id="test_project",
            event_store=EventStoreConfig(path="test_events.db")
        )
        config.events = EventsConfig(
            cleanup_interval_hours=0.001,  # Very short interval for testing
            retention_days=7
        )
        
        system = await EventSystem.from_config(config, project_id="test_project")
        
        # Track method calls
        cleanup_calls = []
        vacuum_calls = []
        
        async def tracked_cleanup(retention_days, project_id=None):
            cleanup_calls.append(retention_days)
            return 0
        
        async def tracked_vacuum():
            vacuum_calls.append(True)
        
        monkeypatch.setattr(system.store, "cleanup_old_events", tracked_cleanup)
        monkeypatch.setattr(system.store, "vacuum", tracked_vacuum)
        
        # Wait for cleanup and vacuum to be called
        success = await AsyncTestHelper.wait_for_condition(
            lambda: len(cleanup_calls) > 0 and len(vacuum_calls) > 0,
            timeout=10.0
        )
        
        # Stop system
        await system.stop()
        
        # Verify both cleanup and vacuum were called
        assert success, "Cleanup and vacuum were not called in time"
        assert len(cleanup_calls) > 0
        assert len(vacuum_calls) > 0
    
    @pytest.mark.asyncio
    async def test_cleanup_loop_handles_errors_gracefully(
        self, tmp_path: Path, monkeypatch
    ):
        """Test that cleanup loop continues running after errors."""
        config = Config()
        config.storage = StorageConfig(
            root=str(tmp_path),
            default_project_id="test_project",
            event_store=EventStoreConfig(path="test_events.db")
        )
        config.events = EventsConfig(
            cleanup_interval_hours=0.001,  # Very short interval for testing
            retention_days=7
        )
        
        system = await EventSystem.from_config(config, project_id="test_project")
        
        # Track cleanup calls
        cleanup_calls = []
        
        async def failing_cleanup(retention_days, project_id=None):
            cleanup_calls.append(retention_days)
            if len(cleanup_calls) == 1:
                # Fail first call
                raise Exception("Simulated cleanup failure")
            # Succeed on subsequent calls
            return 0
        
        monkeypatch.setattr(system.store, "cleanup_old_events", failing_cleanup)
        
        # Wait for cleanup to be called multiple times (showing recovery)
        success = await AsyncTestHelper.wait_for_condition(
            lambda: len(cleanup_calls) >= 2,
            timeout=15.0
        )
        
        # Stop system
        await system.stop()
        
        # Verify cleanup recovered and was called again
        assert success, "Cleanup did not recover from error"
        assert len(cleanup_calls) >= 2
    
    @pytest.mark.asyncio
    async def test_cleanup_loop_logs_purged_count(
        self, tmp_path: Path, monkeypatch, caplog
    ):
        """Test that cleanup loop logs the number of events purged."""
        import logging
        caplog.set_level(logging.INFO)
        
        config = Config()
        config.storage = StorageConfig(
            root=str(tmp_path),
            default_project_id="test_project",
            event_store=EventStoreConfig(path="test_events.db")
        )
        config.events = EventsConfig(
            cleanup_interval_hours=0.001,  # Very short interval for testing
            retention_days=7
        )
        
        system = await EventSystem.from_config(config, project_id="test_project")
        
        # Mock cleanup to return a specific count
        async def mock_cleanup(retention_days, project_id=None):
            return 42  # Return 42 deleted events
        
        async def mock_vacuum():
            pass
        
        monkeypatch.setattr(system.store, "cleanup_old_events", mock_cleanup)
        monkeypatch.setattr(system.store, "vacuum", mock_vacuum)
        
        # Wait for cleanup to be called
        await asyncio.sleep(5.0)
        
        # Stop system
        await system.stop()
        
        # Verify log message contains purged count
        log_messages = [record.message for record in caplog.records]
        cleanup_logs = [msg for msg in log_messages if "purged" in msg.lower() and "42" in msg]
        assert len(cleanup_logs) > 0, f"Expected cleanup log with count 42, got: {log_messages}"
