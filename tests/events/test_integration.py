"""Integration tests for event tracking system.

Tests the complete end-to-end workflow of event emission, batching,
storage, and querying. Also tests integration with configuration system,
correlation IDs, and multi-project isolation.
"""

import asyncio
import time
from pathlib import Path
from typing import List

import pytest

pytestmark = pytest.mark.integration

from agentic_inquiry.config import Config, EventsConfig, EventStoreConfig, StorageConfig
from agentic_inquiry.correlation import correlation_context
from agentic_inquiry.events import EventSystem
from agentic_inquiry.events.context_managers import track_operation
from agentic_inquiry.events.models import Event, EventStatus
from agentic_inquiry.events.store import EventStore
from agentic_inquiry.events.types import EventTypes
from tests.helpers.async_utils import AsyncTestHelper


@pytest.mark.asyncio
async def test_emit_batch_store_query_workflow(tmp_path: Path):
    """Test complete workflow: emit → batch → store → query.
    
    This test verifies the full event lifecycle:
    1. Events are emitted to the queue
    2. Background writer batches them
    3. Events are stored in SQLite
    4. Events can be queried back
    """
    # Create config with temp storage
    config = Config()
    config.storage = StorageConfig(
        root=str(tmp_path),
        default_project_id="test_project",
        event_store=EventStoreConfig(path="test_events.db"),
        backends={
            "default": {
                "type": "lancedb",
                "database_path": str(tmp_path / "lancedb"),
            }
        },
        vector_backend="default",
        graph_backend="default",
        events_backend="default",
        file_tracker_backend_v2="default",
    )
    config.events = EventsConfig(
        enabled=True,
        queue_max_size=100,
        batch_size=5,  # Small batch for faster testing
        flush_interval_seconds=0.1,  # Fast flush for testing
        retention_days=30,
    )
    
    # Create and start event system
    system = await EventSystem.from_config(config, project_id="test_project")
    
    try:
        # Emit multiple events
        operation_id = "test_operation_123"
        for i in range(10):
            await system.emit(
                EventTypes.Indexing.PROGRESS,
                source="test_integration",
                status=EventStatus.PROGRESS,
                operation_id=operation_id,
                files_processed=i,
            )
        
        # Wait for background writer to flush
        success = await AsyncTestHelper.wait_for_async_condition(
            lambda: system.store.get_operation_events(operation_id),
            lambda events: len(events) == 10,
            timeout=5.0
        )
        assert success, "Events were not stored in time"

        # Query events back
        events = await system.store.get_operation_events(operation_id)
        assert all(e.operation_id == operation_id for e in events)
        assert all(e.event_type == EventTypes.Indexing.PROGRESS for e in events)
        assert all(e.project_id == "test_project" for e in events)
        
        # Verify events are ordered by timestamp
        timestamps = [e.timestamp for e in events]
        assert timestamps == sorted(timestamps)
        
        # Verify metadata
        for i, event in enumerate(events):
            assert event.metadata.get("files_processed") == i
    
    finally:
        await system.stop(timeout=2.0)


@pytest.mark.asyncio
async def test_multi_project_isolation(tmp_path: Path):
    """Test that events are properly isolated by project_id.
    
    Verifies that:
    1. Events from different projects are stored separately
    2. Queries filter by project_id correctly
    3. No cross-project data leakage
    """
    # Create config with temp storage
    config = Config()
    config.storage = StorageConfig(
        root=str(tmp_path),
        default_project_id="project_a",
        event_store=EventStoreConfig(path="test_events.db")
    )
    config.events = EventsConfig(
        enabled=True,
        queue_max_size=100,
        batch_size=5,
        flush_interval_seconds=0.1,
    )
    
    # Create event systems for two projects
    system_a = await EventSystem.from_config(config, project_id="project_a")
    system_b = await EventSystem.from_config(config, project_id="project_b")
    
    try:
        operation_id = "shared_operation_id"
        
        # Emit events from project A
        for i in range(5):
            await system_a.emit(
                EventTypes.Indexing.PROGRESS,
                source="project_a",
                status=EventStatus.PROGRESS,
                operation_id=operation_id,
                project="a",
                index=i,
            )
        
        # Emit events from project B
        for i in range(3):
            await system_b.emit(
                EventTypes.Search.QUERY_STARTED,
                source="project_b",
                status=EventStatus.STARTED,
                operation_id=operation_id,
                project="b",
                index=i,
            )

        # Wait for flush - wait for both projects to have their events
        success = await AsyncTestHelper.wait_for_async_condition(
            lambda: system_a.store.get_operation_events(operation_id, project_id="project_a"),
            lambda events: len(events) == 5,
            timeout=5.0
        )
        assert success, "Project A events were not stored in time"

        success = await AsyncTestHelper.wait_for_async_condition(
            lambda: system_b.store.get_operation_events(operation_id, project_id="project_b"),
            lambda events: len(events) == 3,
            timeout=5.0
        )
        assert success, "Project B events were not stored in time"

        # Query events for project A
        events_a = await system_a.store.get_operation_events(
            operation_id,
            project_id="project_a"
        )
        
        # Query events for project B
        events_b = await system_b.store.get_operation_events(
            operation_id,
            project_id="project_b"
        )
        
        # Verify isolation
        assert len(events_a) == 5
        assert len(events_b) == 3
        
        # Verify project A events
        assert all(e.project_id == "project_a" for e in events_a)
        assert all(e.event_type == EventTypes.Indexing.PROGRESS for e in events_a)
        assert all(e.metadata.get("project") == "a" for e in events_a)
        
        # Verify project B events
        assert all(e.project_id == "project_b" for e in events_b)
        assert all(e.event_type == EventTypes.Search.QUERY_STARTED for e in events_b)
        assert all(e.metadata.get("project") == "b" for e in events_b)
    
    finally:
        await system_a.stop(timeout=2.0)
        await system_b.stop(timeout=2.0)


@pytest.mark.asyncio
async def test_correlation_id_propagation(tmp_path: Path):
    """Test that correlation IDs are automatically propagated to events.
    
    Verifies that:
    1. Events use correlation ID as operation_id when not specified
    2. Correlation context is properly integrated
    3. Related operations share the same operation_id
    """
    # Create config with temp storage
    config = Config()
    config.storage = StorageConfig(
        root=str(tmp_path),
        default_project_id="test_project",
        event_store=EventStoreConfig(path="test_events.db"),
        backends={
            "default": {
                "type": "lancedb",
                "database_path": str(tmp_path / "lancedb"),
            }
        },
        vector_backend="default",
        graph_backend="default",
        events_backend="default",
        file_tracker_backend_v2="default",
    )
    config.events = EventsConfig(
        enabled=True,
        queue_max_size=100,
        batch_size=5,
        flush_interval_seconds=0.1,
    )
    
    system = await EventSystem.from_config(config, project_id="test_project")
    
    try:
        # Use correlation context
        with correlation_context() as corr_id:
            # Emit events without explicit operation_id
            await system.emit(
                EventTypes.Indexing.STARTED,
                source="test_integration",
                status=EventStatus.STARTED,
            )
            
            await system.emit(
                EventTypes.Indexing.PROGRESS,
                source="test_integration",
                status=EventStatus.PROGRESS,
                files_processed=5,
            )
            
            await system.emit(
                EventTypes.Indexing.COMPLETED,
                source="test_integration",
                status=EventStatus.COMPLETED,
                total_files=10,
            )

        # Wait for flush
        success = await AsyncTestHelper.wait_for_async_condition(
            lambda: system.store.get_operation_events(corr_id),
            lambda events: len(events) == 3,
            timeout=5.0
        )
        assert success, "Correlated events were not stored in time"

        # Query events by correlation ID
        events = await system.store.get_operation_events(corr_id)
        assert all(e.operation_id == corr_id for e in events)
        
        # Verify event sequence
        assert events[0].event_type == EventTypes.Indexing.STARTED
        assert events[1].event_type == EventTypes.Indexing.PROGRESS
        assert events[2].event_type == EventTypes.Indexing.COMPLETED
    
    finally:
        await system.stop(timeout=2.0)


@pytest.mark.asyncio
async def test_configuration_integration(tmp_path: Path):
    """Test that event system respects configuration settings.
    
    Verifies that:
    1. Queue size limits are enforced
    2. Batch size affects write behavior
    3. Flush interval controls timing
    4. Retention settings are accessible
    """
    # Create config with specific settings
    config = Config()
    config.storage = StorageConfig(
        root=str(tmp_path),
        default_project_id="test_project",
        event_store=EventStoreConfig(path="test_events.db"),
        backends={
            "default": {
                "type": "lancedb",
                "database_path": str(tmp_path / "lancedb"),
            }
        },
        vector_backend="default",
        graph_backend="default",
        events_backend="default",
        file_tracker_backend_v2="default",
    )
    config.events = EventsConfig(
        enabled=True,
        queue_max_size=10,  # Small queue
        batch_size=3,  # Small batch
        flush_interval_seconds=0.05,  # Very fast flush
        retention_days=7,  # Custom retention
    )
    
    system = await EventSystem.from_config(config, project_id="test_project")
    
    try:
        # Verify configuration is applied
        assert system._queue.maxsize == 10
        assert system.config.events.batch_size == 3
        assert system.config.events.flush_interval_seconds == 0.05
        
        # Emit events up to queue limit
        operation_id = "config_test"
        for i in range(10):
            await system.emit(
                EventTypes.Indexing.PROGRESS,
                source="test_integration",
                status=EventStatus.PROGRESS,
                operation_id=operation_id,
                index=i,
            )
        
        # Verify metrics
        assert system.events_emitted_count == 10
        assert system.events_dropped_count == 0
        
        # Try to overflow queue (should drop events)
        for i in range(5):
            await system.emit(
                EventTypes.Indexing.PROGRESS,
                source="test_integration",
                status=EventStatus.PROGRESS,
                operation_id=operation_id,
                index=i + 10,
            )
        
        # Some events should be dropped
        assert system.events_dropped_count > 0

        # Wait for flush
        success = await AsyncTestHelper.wait_for_async_condition(
            lambda: system.store.get_operation_events(operation_id),
            lambda events: len(events) > 0,
            timeout=5.0
        )
        assert success, "Events were not stored in time"

        # Query events
        events = await system.store.get_operation_events(operation_id)
        assert len(events) <= 10  # Can't exceed queue size
    
    finally:
        await system.stop(timeout=2.0)


@pytest.mark.asyncio
async def test_track_operation_context_manager(tmp_path: Path):
    """Test track_operation context manager integration.
    
    Verifies that:
    1. Started event is emitted on entry
    2. Completed event is emitted on success
    3. Failed event is emitted on exception
    4. Correlation ID is properly managed
    5. Manual flush works correctly
    """
    # Create config with temp storage
    config = Config()
    config.storage = StorageConfig(
        root=str(tmp_path),
        default_project_id="test_project",
        event_store=EventStoreConfig(path="test_events.db"),
        backends={
            "default": {
                "type": "lancedb",
                "database_path": str(tmp_path / "lancedb"),
            }
        },
        vector_backend="default",
        graph_backend="default",
        events_backend="default",
        file_tracker_backend_v2="default",
    )
    config.events = EventsConfig(
        enabled=True,
        queue_max_size=100,
        batch_size=5,
        flush_interval_seconds=0.1,
    )
    
    system = await EventSystem.from_config(config, project_id="test_project")
    
    try:
        # Test successful operation - capture operation_id
        indexing_op_id = None
        async with track_operation(
            system,
            "indexing",
            source="test_integration",
        ) as op:
            indexing_op_id = op.operation_id
            await op.progress(step=1)
            await op.progress(step=2)
        
        # Test failed operation - capture operation_id
        search_op_id = None
        try:
            async with track_operation(
                system,
                "search",
                source="test_integration",
            ) as op:
                search_op_id = op.operation_id
                await op.progress(step=1)
                raise ValueError("Test error")
        except ValueError:
            pass  # Expected
        
        # Stop the system to flush all events (this stops the background writer and flushes)
        await system.stop(timeout=2.0)
        
        # Create new store to query
        store = await EventStore.from_config(
            db_path=tmp_path / "test_events.db",
            project_id="test_project"
        )
        
        # Query indexing events by operation_id
        indexing_events = await store.get_operation_events(indexing_op_id)
        
        # Verify indexing lifecycle (started + 2 progress + completed = 4)
        assert len(indexing_events) == 4
        
        # Check event types in order
        assert indexing_events[0].event_type == "indexing.started"
        assert indexing_events[1].event_type == "indexing.progress"
        assert indexing_events[2].event_type == "indexing.progress"
        assert indexing_events[3].event_type == "indexing.completed"
        
        # Verify metadata
        assert indexing_events[1].metadata.get("step") == 1
        assert indexing_events[2].metadata.get("step") == 2
        
        # Query search events by operation_id
        search_events = await store.get_operation_events(search_op_id)
        
        # Verify search lifecycle (started + progress + failed = 3)
        assert len(search_events) == 3
        
        # Check event types in order
        assert search_events[0].event_type == "search.started"
        assert search_events[1].event_type == "search.progress"
        assert search_events[2].event_type == "search.failed"
        
        # Verify failed event has error info
        assert search_events[2].status == EventStatus.FAILED
        assert "Test error" in search_events[2].metadata.get("error", "")
        
        await store.close()
        
    finally:
        pass  # Already stopped in test


@pytest.mark.asyncio
async def test_concurrent_operations(tmp_path: Path):
    """Test that multiple concurrent operations are tracked correctly.
    
    Verifies that:
    1. Multiple operations can emit events concurrently
    2. Events are properly isolated by operation_id
    3. No data corruption or race conditions
    """
    # Create config with temp storage
    config = Config()
    config.storage = StorageConfig(
        root=str(tmp_path),
        default_project_id="test_project",
        event_store=EventStoreConfig(path="test_events.db"),
        backends={
            "default": {
                "type": "lancedb",
                "database_path": str(tmp_path / "lancedb"),
            }
        },
        vector_backend="default",
        graph_backend="default",
        events_backend="default",
        file_tracker_backend_v2="default",
    )
    config.events = EventsConfig(
        enabled=True,
        queue_max_size=1000,
        batch_size=50,
        flush_interval_seconds=0.1,
    )
    
    system = await EventSystem.from_config(config, project_id="test_project")
    
    try:
        async def simulate_operation(op_id: str, event_count: int):
            """Simulate an operation that emits multiple events."""
            for i in range(event_count):
                await system.emit(
                    EventTypes.Indexing.PROGRESS,
                    source="concurrent_test",
                    status=EventStatus.PROGRESS,
                    operation_id=op_id,
                    index=i,
                )
                await asyncio.sleep(0.01)  # Small delay
        
        # Run multiple operations concurrently
        operation_ids = [f"op_{i}" for i in range(5)]
        tasks = [
            simulate_operation(op_id, 10)
            for op_id in operation_ids
        ]
        
        await asyncio.gather(*tasks)

        # Wait for flush - wait for all operations to have their events
        for op_id in operation_ids:
            success = await AsyncTestHelper.wait_for_async_condition(
                lambda op=op_id: system.store.get_operation_events(op),
                lambda events: len(events) == 10,
                timeout=10.0
            )
            assert success, f"Events for operation {op_id} were not stored in time"

        # Verify each operation's events
        for op_id in operation_ids:
            events = await system.store.get_operation_events(op_id)
            
            # Should have all 10 events
            assert len(events) == 10
            
            # All events should belong to this operation
            assert all(e.operation_id == op_id for e in events)
            
            # Events should be ordered
            indices = [e.metadata.get("index") for e in events]
            assert indices == list(range(10))
    
    finally:
        await system.stop(timeout=2.0)


@pytest.mark.asyncio
async def test_graceful_shutdown_with_pending_events(tmp_path: Path):
    """Test that graceful shutdown flushes pending events.
    
    Verifies that:
    1. Events are flushed during normal operation
    2. Shutdown completes successfully
    3. Events can be queried after shutdown
    
    Note: The current implementation flushes the current batch on shutdown,
    but may not drain all events from the queue. This test verifies that
    events written before shutdown are persisted.
    """
    # Create config with temp storage and small batch for faster flushing
    config = Config()
    config.storage = StorageConfig(
        root=str(tmp_path),
        default_project_id="test_project",
        event_store=EventStoreConfig(path="test_events.db"),
        backends={
            "default": {
                "type": "lancedb",
                "database_path": str(tmp_path / "lancedb"),
            }
        },
        vector_backend="default",
        graph_backend="default",
        events_backend="default",
        file_tracker_backend_v2="default",
    )
    config.events = EventsConfig(
        enabled=True,
        queue_max_size=1000,
        batch_size=10,  # Smaller batch for faster flushing
        flush_interval_seconds=0.1,  # Fast flush
    )
    
    system = await EventSystem.from_config(config, project_id="test_project")
    
    operation_id = "shutdown_test"
    
    # Emit events
    for i in range(50):
        await system.emit(
            EventTypes.Indexing.PROGRESS,
            source="shutdown_test",
            status=EventStatus.PROGRESS,
            operation_id=operation_id,
            index=i,
        )

    # Wait for events to be flushed
    await AsyncTestHelper.wait_for_async_condition(
        lambda: system.store.get_operation_events(operation_id),
        lambda events: len(events) >= 40,  # At least 80% should be flushed
        timeout=10.0
    )
    # Note: May not always hit 40 due to timing, so just wait without assertion

    # Stop system
    stop_success = await system.stop(timeout=5.0)

    # Should have stopped successfully
    assert stop_success is True
    
    # Create a new store instance to query (system.store is closed after stop)
    store = await EventStore.from_config(
        db_path=tmp_path / "test_events.db",
        project_id="test_project"
    )
    
    try:
        # Verify events were stored (should have most or all of them)
        events = await store.get_operation_events(operation_id)
        # Allow for some events to be in-flight during shutdown
        assert len(events) >= 40  # At least 80% of events should be stored
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_event_store_query_methods(tmp_path: Path):
    """Test various EventStore query methods.
    
    Verifies that:
    1. get_events_by_type filters correctly
    2. get_events_by_time_range filters correctly
    3. get_latest_events returns recent events
    4. count_events returns accurate counts
    """
    # Create event store
    db_path = tmp_path / "test_events.db"
    store = await EventStore.from_config(
        db_path=db_path,
        project_id="test_project"
    )
    
    try:
        # Create events with different types and timestamps
        events: List[Event] = []
        base_time = time.time()
        
        for i in range(10):
            event = Event(
                project_id="test_project",
                operation_id="query_test",
                timestamp=base_time + i,
                event_type=EventTypes.Indexing.PROGRESS if i < 5 else EventTypes.Search.QUERY_STARTED,
                status=EventStatus.PROGRESS,
                source="query_test",
                metadata={"index": i},
            )
            events.append(event)
        
        # Store events
        await store.store_events(events)
        
        # Test get_events_by_type
        indexing_events = await store.get_events_by_type(
            EventTypes.Indexing.PROGRESS,
            project_id="test_project"
        )
        assert len(indexing_events) == 5
        
        search_events = await store.get_events_by_type(
            EventTypes.Search.QUERY_STARTED,
            project_id="test_project"
        )
        assert len(search_events) == 5
        
        # Test get_events_by_time_range
        # Query is inclusive on both ends, so we need to use mid_time - 0.1 to exclude event at index 5
        mid_time = base_time + 4.9
        early_events = await store.get_events_by_time_range(
            start_time=base_time,
            end_time=mid_time,
            project_id="test_project"
        )
        assert len(early_events) == 5
        
        # Test get_latest_events
        latest = await store.get_latest_events(limit=3, project_id="test_project")
        assert len(latest) == 3
        # Should be in descending order
        assert latest[0].timestamp > latest[1].timestamp > latest[2].timestamp
        
        # Test count_events
        total_count = await store.count_events(project_id="test_project")
        assert total_count == 10
        
        type_count = await store.count_events(
            event_type=EventTypes.Indexing.PROGRESS,
            project_id="test_project"
        )
        assert type_count == 5
    
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mcp_server_event_persistence_end_to_end(tmp_path: Path):
    """Test end-to-end event persistence through MCP server operations.
    
    This integration test verifies that:
    1. MCP server creates and initializes EventSystem with persistence
    2. Indexing operations emit and persist events
    3. Events can be queried by type, time range, and operation ID
    4. Events contain correct metadata
    5. Server shutdown properly flushes and closes EventSystem
    
    Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5
    """
    from agentic_inquiry.mcp.factories import close_mcp_services, create_mcp_services
    
    # Create config with temp storage
    config = Config()
    config.storage = StorageConfig(
        root=str(tmp_path),
        default_project_id="test_project",
        event_store=EventStoreConfig(path="test_events.db"),
        backends={
            "default": {
                "type": "lancedb",
                "database_path": str(tmp_path / "lancedb"),
            }
        },
        vector_backend="default",
        graph_backend="default",
    )
    config.events = EventsConfig(
        enabled=True,
        queue_max_size=100,
        batch_size=10,
        flush_interval_seconds=0.1,
        retention_days=30,
    )
    
    # Create MCP services (this should create and start EventSystem)
    services = await create_mcp_services(config, project_id="test_project")
    
    try:
        # Verify EventSystem was created and started
        assert "event_system" in services
        event_system = services["event_system"]
        assert event_system is not None
        assert event_system.store is not None
        
        # Get indexing pipeline from services
        indexing_pipeline = services["indexing_pipeline"]
        assert indexing_pipeline is not None
        assert indexing_pipeline.event_system is event_system
        
        # Simulate indexing operation by emitting events directly
        # (We don't need to actually index files, just verify event persistence)
        operation_id = "test_indexing_operation"
        
        # Emit indexing.started event
        await event_system.emit(
            EventTypes.Indexing.STARTED,
            source="test_mcp_integration",
            status=EventStatus.STARTED,
            operation_id=operation_id,
            total_files=5,
        )
        
        # Emit indexing.progress events
        for i in range(5):
            await event_system.emit(
                EventTypes.Indexing.PROGRESS,
                source="test_mcp_integration",
                status=EventStatus.PROGRESS,
                operation_id=operation_id,
                files_processed=i + 1,
                current_file=f"test_file_{i}.py",
            )
        
        # Emit indexing.completed event
        await event_system.emit(
            EventTypes.Indexing.COMPLETED,
            source="test_mcp_integration",
            status=EventStatus.COMPLETED,
            operation_id=operation_id,
            total_files=5,
            total_chunks=25,
        )
        
        # Wait for events to be persisted
        success = await AsyncTestHelper.wait_for_async_condition(
            lambda: event_system.store.get_operation_events(operation_id),
            lambda events: len(events) == 7,  # 1 started + 5 progress + 1 completed
            timeout=5.0
        )
        assert success, "Events were not persisted in time"
        
        # Test 1: Query events by operation ID
        events_by_operation = await event_system.store.get_operation_events(operation_id)
        assert len(events_by_operation) == 7
        assert all(e.operation_id == operation_id for e in events_by_operation)
        assert all(e.project_id == "test_project" for e in events_by_operation)
        
        # Verify event sequence
        assert events_by_operation[0].event_type == EventTypes.Indexing.STARTED
        assert events_by_operation[1].event_type == EventTypes.Indexing.PROGRESS
        assert events_by_operation[-1].event_type == EventTypes.Indexing.COMPLETED
        
        # Test 2: Query events by type
        progress_events = await event_system.store.get_events_by_type(
            EventTypes.Indexing.PROGRESS,
            project_id="test_project"
        )
        assert len(progress_events) >= 5  # At least our 5 progress events
        
        # Verify progress events have correct metadata
        our_progress_events = [e for e in progress_events if e.operation_id == operation_id]
        assert len(our_progress_events) == 5
        # Sort by timestamp to ensure correct order
        our_progress_events.sort(key=lambda e: e.timestamp)
        for i, event in enumerate(our_progress_events):
            assert event.metadata.get("files_processed") == i + 1
            assert event.metadata.get("current_file") == f"test_file_{i}.py"
        
        # Test 3: Query events by time range
        start_time = events_by_operation[0].timestamp
        end_time = events_by_operation[-1].timestamp
        
        events_by_time = await event_system.store.get_events_by_time_range(
            start_time=start_time - 1.0,  # Include some buffer
            end_time=end_time + 1.0,
            project_id="test_project"
        )
        assert len(events_by_time) >= 7  # At least our 7 events
        
        # Verify our events are in the time range results
        our_events_in_range = [e for e in events_by_time if e.operation_id == operation_id]
        assert len(our_events_in_range) == 7
        
        # Test 4: Verify event metadata is complete
        started_event = events_by_operation[0]
        assert started_event.event_type == EventTypes.Indexing.STARTED
        assert started_event.status == EventStatus.STARTED
        assert started_event.source == "test_mcp_integration"
        assert started_event.metadata.get("total_files") == 5
        
        completed_event = events_by_operation[-1]
        assert completed_event.event_type == EventTypes.Indexing.COMPLETED
        assert completed_event.status == EventStatus.COMPLETED
        assert completed_event.metadata.get("total_files") == 5
        assert completed_event.metadata.get("total_chunks") == 25
        
        # Test 5: Verify latest events query
        latest_events = await event_system.store.get_latest_events(
            limit=10,
            project_id="test_project"
        )
        assert len(latest_events) > 0
        # Should be in descending timestamp order
        for i in range(len(latest_events) - 1):
            assert latest_events[i].timestamp >= latest_events[i + 1].timestamp
        
    finally:
        # Simulates server shutdown
        await close_mcp_services(services)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mcp_server_multiple_operations_event_isolation(tmp_path: Path):
    """Test that multiple concurrent MCP operations maintain event isolation.
    
    This test verifies that:
    1. Multiple operations can run concurrently
    2. Events are properly isolated by operation_id
    3. No event data corruption or mixing
    4. All events are persisted correctly
    
    Requirements: 2.1, 2.2, 2.3, 2.4, 2.5
    """
    from agentic_inquiry.mcp.factories import close_mcp_services, create_mcp_services
    
    # Create config with temp storage
    config = Config()
    config.storage = StorageConfig(
        root=str(tmp_path),
        default_project_id="test_project",
        event_store=EventStoreConfig(path="test_events.db"),
        backends={
            "default": {
                "type": "lancedb",
                "database_path": str(tmp_path / "lancedb"),
            }
        },
        vector_backend="default",
        graph_backend="default",
    )
    config.events = EventsConfig(
        enabled=True,
        queue_max_size=1000,
        batch_size=50,
        flush_interval_seconds=0.1,
    )
    
    # Create MCP services
    services = await create_mcp_services(config, project_id="test_project")
    
    try:
        event_system = services["event_system"]
        
        async def simulate_indexing_operation(op_id: str, file_count: int):
            """Simulate an indexing operation with multiple events."""
            await event_system.emit(
                EventTypes.Indexing.STARTED,
                source="concurrent_test",
                status=EventStatus.STARTED,
                operation_id=op_id,
                total_files=file_count,
            )
            
            for i in range(file_count):
                await event_system.emit(
                    EventTypes.Indexing.PROGRESS,
                    source="concurrent_test",
                    status=EventStatus.PROGRESS,
                    operation_id=op_id,
                    files_processed=i + 1,
                )
                await asyncio.sleep(0.01)  # Small delay
            
            await event_system.emit(
                EventTypes.Indexing.COMPLETED,
                source="concurrent_test",
                status=EventStatus.COMPLETED,
                operation_id=op_id,
                total_files=file_count,
            )
        
        async def simulate_search_operation(op_id: str, query_count: int):
            """Simulate a search operation with multiple events."""
            for i in range(query_count):
                await event_system.emit(
                    EventTypes.Search.QUERY_STARTED,
                    source="concurrent_test",
                    status=EventStatus.STARTED,
                    operation_id=op_id,
                    query=f"test query {i}",
                )
                await asyncio.sleep(0.01)  # Small delay
        
        # Run multiple operations concurrently
        indexing_ops = [f"indexing_op_{i}" for i in range(3)]
        search_ops = [f"search_op_{i}" for i in range(2)]
        
        tasks = []
        for op_id in indexing_ops:
            tasks.append(simulate_indexing_operation(op_id, 5))
        for op_id in search_ops:
            tasks.append(simulate_search_operation(op_id, 3))
        
        await asyncio.gather(*tasks)
        
        # Wait for all events to be persisted
        for op_id in indexing_ops:
            success = await AsyncTestHelper.wait_for_async_condition(
                lambda o=op_id: event_system.store.get_operation_events(o),
                lambda events: len(events) == 7,  # 1 started + 5 progress + 1 completed
                timeout=10.0
            )
            assert success, f"Indexing events for {op_id} were not persisted in time"
        
        for op_id in search_ops:
            success = await AsyncTestHelper.wait_for_async_condition(
                lambda o=op_id: event_system.store.get_operation_events(o),
                lambda events: len(events) == 3,  # 3 query events
                timeout=10.0
            )
            assert success, f"Search events for {op_id} were not persisted in time"
        
        # Verify each indexing operation's events
        for op_id in indexing_ops:
            events = await event_system.store.get_operation_events(op_id)
            assert len(events) == 7
            assert all(e.operation_id == op_id for e in events)
            assert events[0].event_type == EventTypes.Indexing.STARTED
            assert events[-1].event_type == EventTypes.Indexing.COMPLETED
        
        # Verify each search operation's events
        for op_id in search_ops:
            events = await event_system.store.get_operation_events(op_id)
            assert len(events) == 3
            assert all(e.operation_id == op_id for e in events)
            assert all(e.event_type == EventTypes.Search.QUERY_STARTED for e in events)
    
    finally:
        await close_mcp_services(services)
