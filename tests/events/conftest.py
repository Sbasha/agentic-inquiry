"""Pytest fixtures for event system tests."""

import asyncio
import time
from pathlib import Path
from typing import AsyncIterator

import pytest_asyncio

from agentic_inquiry.events.models import Event, EventStatus
from agentic_inquiry.events.store import EventStore
from agentic_inquiry.events.system import EventSystem


# Note: pytest_sessionfinish is handled by the root tests/conftest.py
# which performs comprehensive cleanup of executors and threads.
# This file only contains event-specific fixtures.


@pytest_asyncio.fixture(autouse=True)
async def cleanup_pending_tasks():
    """Cleanup any pending asyncio tasks after each test.

    This fixture ensures that stray background tasks created during tests
    are properly cancelled and don't prevent the event loop from closing.
    """
    # Get tasks before the test (excluding current task)
    current_task = asyncio.current_task()
    before_tasks = {t for t in asyncio.all_tasks() if t is not current_task}

    yield

    # Get tasks after the test
    after_tasks = {t for t in asyncio.all_tasks() if t is not current_task}

    # Cancel any new tasks created during the test
    new_tasks = after_tasks - before_tasks
    for task in new_tasks:
        if not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=0.5)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception:
                pass


# Removed clear_shared_event_systems fixture - MinimalEventSystem has been removed
# All components now use the full EventSystem which is properly managed via dependency injection


@pytest_asyncio.fixture
async def temp_event_store(tmp_path: Path) -> AsyncIterator[EventStore]:
    """Create temporary event store for testing.
    
    This fixture provides an EventStore instance backed by a temporary
    SQLite database that is automatically cleaned up after the test.
    
    Args:
        tmp_path: pytest's tmp_path fixture providing a temporary directory
        
    Yields:
        EventStore instance ready for use in tests
    """
    db_path = tmp_path / "test_events.db"
    store = await EventStore.from_config(
        db_path=db_path,
        project_id="test_project"
    )
    yield store
    await store.close()


@pytest_asyncio.fixture
async def event_system(tmp_path: Path) -> AsyncIterator[EventSystem]:
    """Create event system with temp storage.
    
    This fixture provides a fully initialized EventSystem with temporary
    storage, ready for testing event emission and querying. The background
    writer task is started automatically and stopped on cleanup.
    
    Args:
        tmp_path: pytest's tmp_path fixture providing a temporary directory
        
    Yields:
        EventSystem instance ready for use in tests
    """
    from agentic_inquiry.config import Config, StorageConfig, EventStoreConfig, EventsConfig
    
    # Create config with temp storage
    config = Config()
    config.storage = StorageConfig(
        root=str(tmp_path),
        default_project_id="test_project",
        event_store=EventStoreConfig(path="test_events.db")
    )
    config.events = EventsConfig(
        enabled=True,
        queue_max_size=100,
        batch_size=10,
        flush_interval_seconds=0.1,  # Fast flush for tests
        retention_days=30,
        sampling_enabled=False,
    )
    
    # Create and start event system
    system = await EventSystem.from_config(config, project_id="test_project")
    yield system
    await system.stop(timeout=2.0)


@pytest_asyncio.fixture
def sample_event() -> Event:
    """Create a sample event for testing.
    
    This fixture provides a basic Event instance with sensible defaults
    that can be used in tests or modified as needed.
    
    Returns:
        Event instance with test data
    """
    return Event(
        project_id="test_project",
        operation_id="test_operation",
        session_id="test_session",
        timestamp=time.time(),
        event_type="test.event",
        status=EventStatus.PROGRESS,
        source="test_source",
        metadata={"test_key": "test_value"},
        schema_version="1.0",
    )
