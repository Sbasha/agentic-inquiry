"""Test utilities for event system testing."""

import pytest

pytestmark = pytest.mark.unit

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, List, Optional

from agentic_inquiry.events.models import Event, EventStatus
from agentic_inquiry.events.system import EventSystem


class EventCapture:
    """Context manager for capturing events during tests.
    
    This utility allows tests to capture events emitted during a block
    of code execution, making it easy to verify that the correct events
    were emitted with the expected data.
    
    Example:
        async with event_capture(event_system) as captured:
            await some_operation()
        
        assert len(captured) == 2
        assert captured[0].event_type == "operation.started"
        assert captured[1].event_type == "operation.completed"
    """
    
    def __init__(self, event_system: EventSystem):
        """Initialize event capture.
        
        Args:
            event_system: EventSystem instance to capture events from
        """
        self.event_system = event_system
        self.captured_events: List[Event] = []
        self._original_emit = None
    
    async def __aenter__(self) -> List[Event]:
        """Enter context and start capturing events."""
        # Save original emit method
        self._original_emit = self.event_system.emit
        
        # Replace with capturing version
        async def capturing_emit(
            event_type: str,
            source: str,
            status: EventStatus = EventStatus.PROGRESS,
            operation_id: Optional[str] = None,
            session_id: Optional[str] = None,
            **metadata: Any,
        ) -> None:
            """Capture event instead of emitting to queue."""
            from agentic_inquiry.correlation import get_correlation_id
            
            if operation_id is None:
                operation_id = get_correlation_id()
            
            event = Event(
                project_id=self.event_system.project_id,
                event_type=event_type,
                source=source,
                status=status,
                operation_id=operation_id,
                session_id=session_id,
                metadata=metadata,
            )
            self.captured_events.append(event)
        
        self.event_system.emit = capturing_emit
        return self.captured_events
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context and restore original emit method."""
        if self._original_emit:
            self.event_system.emit = self._original_emit


@asynccontextmanager
async def event_capture(event_system: EventSystem) -> AsyncIterator[List[Event]]:
    """Context manager for capturing events during tests.
    
    This is a convenience wrapper around EventCapture that can be used
    directly as an async context manager.
    
    Args:
        event_system: EventSystem instance to capture events from
        
    Yields:
        List of captured Event instances
        
    Example:
        async with event_capture(event_system) as captured:
            await pipeline.index_file("test.py")
        
        assert len(captured) == 3
        assert captured[0].event_type == "indexing.started"
    """
    capture = EventCapture(event_system)
    async with capture as captured:
        yield captured


def create_test_event(
    event_type: str = "test.event",
    source: str = "test",
    status: EventStatus = EventStatus.PROGRESS,
    project_id: str = "test_project",
    operation_id: Optional[str] = None,
    session_id: Optional[str] = None,
    timestamp: Optional[float] = None,
    **metadata: Any,
) -> Event:
    """Create a test event with sensible defaults.
    
    This helper function simplifies creating Event instances in tests
    by providing sensible defaults for all required fields.
    
    Args:
        event_type: Event type string (default: "test.event")
        source: Source component (default: "test")
        status: Event status (default: PROGRESS)
        project_id: Project identifier (default: "test_project")
        operation_id: Optional operation ID
        session_id: Optional session ID
        timestamp: Optional timestamp (defaults to current time)
        **metadata: Additional metadata fields
        
    Returns:
        Event instance configured for testing
        
    Example:
        event = create_test_event(
            event_type="indexing.started",
            source="pipeline",
            status=EventStatus.STARTED,
            file_path="/path/to/file.py"
        )
    """
    if timestamp is None:
        timestamp = time.time()
    
    return Event(
        project_id=project_id,
        operation_id=operation_id,
        session_id=session_id,
        timestamp=timestamp,
        event_type=event_type,
        status=status,
        source=source,
        metadata=metadata,
    )


def create_test_events(
    count: int,
    event_type: str = "test.event",
    source: str = "test",
    project_id: str = "test_project",
    operation_id: Optional[str] = None,
    base_timestamp: Optional[float] = None,
    **metadata: Any,
) -> List[Event]:
    """Create multiple test events with sequential timestamps.
    
    This helper function creates a list of events with incrementing
    timestamps, useful for testing time-based queries and ordering.
    
    Args:
        count: Number of events to create
        event_type: Event type string (default: "test.event")
        source: Source component (default: "test")
        project_id: Project identifier (default: "test_project")
        operation_id: Optional operation ID (same for all events)
        base_timestamp: Starting timestamp (defaults to current time)
        **metadata: Additional metadata fields (same for all events)
        
    Returns:
        List of Event instances with sequential timestamps
        
    Example:
        events = create_test_events(
            count=5,
            event_type="indexing.progress",
            source="pipeline",
            operation_id="op123",
            files_processed=10
        )
    """
    if base_timestamp is None:
        base_timestamp = time.time()
    
    events = []
    for i in range(count):
        event = Event(
            project_id=project_id,
            operation_id=operation_id or f"op_{i}",
            timestamp=base_timestamp + i,
            event_type=event_type,
            status=EventStatus.PROGRESS,
            source=source,
            metadata=metadata.copy() if metadata else {},
        )
        events.append(event)
    
    return events


def create_operation_events(
    operation_id: str,
    operation_type: str = "test",
    source: str = "test",
    project_id: str = "test_project",
    include_progress: bool = True,
    fail: bool = False,
    base_timestamp: Optional[float] = None,
    **metadata: Any,
) -> List[Event]:
    """Create a complete set of events for an operation lifecycle.
    
    This helper creates a realistic sequence of events for an operation,
    including started, optional progress, and completed/failed events.
    
    Args:
        operation_id: Operation identifier
        operation_type: Base operation type (e.g., "indexing", "search")
        source: Source component
        project_id: Project identifier
        include_progress: Whether to include progress events (default: True)
        fail: Whether operation should fail (default: False)
        base_timestamp: Starting timestamp (defaults to current time)
        **metadata: Additional metadata for events
        
    Returns:
        List of Event instances representing operation lifecycle
        
    Example:
        events = create_operation_events(
            operation_id="op123",
            operation_type="indexing",
            source="pipeline",
            include_progress=True,
            fail=False,
            files_total=10
        )
    """
    if base_timestamp is None:
        base_timestamp = time.time()
    
    events = []
    
    # Started event
    events.append(Event(
        project_id=project_id,
        operation_id=operation_id,
        timestamp=base_timestamp,
        event_type=f"{operation_type}.started",
        status=EventStatus.STARTED,
        source=source,
        metadata=metadata.copy() if metadata else {},
    ))
    
    # Progress events
    if include_progress:
        for i in range(1, 3):
            progress_metadata = metadata.copy() if metadata else {}
            progress_metadata["progress"] = i * 33
            events.append(Event(
                project_id=project_id,
                operation_id=operation_id,
                timestamp=base_timestamp + i,
                event_type=f"{operation_type}.progress",
                status=EventStatus.PROGRESS,
                source=source,
                metadata=progress_metadata,
            ))
    
    # Final event (completed or failed)
    final_timestamp = base_timestamp + (3 if include_progress else 1)
    if fail:
        final_metadata = metadata.copy() if metadata else {}
        final_metadata["error"] = "Test error"
        events.append(Event(
            project_id=project_id,
            operation_id=operation_id,
            timestamp=final_timestamp,
            event_type=f"{operation_type}.failed",
            status=EventStatus.FAILED,
            source=source,
            metadata=final_metadata,
        ))
    else:
        events.append(Event(
            project_id=project_id,
            operation_id=operation_id,
            timestamp=final_timestamp,
            event_type=f"{operation_type}.completed",
            status=EventStatus.COMPLETED,
            source=source,
            metadata=metadata.copy() if metadata else {},
        ))
    
    return events


async def wait_for_events(
    event_system: EventSystem,
    timeout: float = 2.0,
) -> None:
    """Wait for event system to flush all pending events.
    
    This utility waits for the event system's queue to be empty and
    gives the background writer time to process all events. Useful
    in tests to ensure events are persisted before querying.
    
    Args:
        event_system: EventSystem instance
        timeout: Maximum time to wait in seconds (default: 2.0)
        
    Raises:
        asyncio.TimeoutError: If queue doesn't empty within timeout
        
    Example:
        await event_system.emit("test.event", source="test")
        await wait_for_events(event_system)
        # Now safe to query events from store
    """
    loop = asyncio.get_running_loop()
    start_time = loop.time()
    
    while event_system._queue.qsize() > 0:
        if loop.time() - start_time > timeout:
            raise asyncio.TimeoutError(
                f"Event queue did not empty within {timeout}s "
                f"(remaining: {event_system._queue.qsize()})"
            )
        await asyncio.sleep(0.01)
    
    # Give writer task time to process
    await asyncio.sleep(0.1)
