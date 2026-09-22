"""Context managers for operation tracking.

This module provides context managers that simplify tracking operation lifecycles
by automatically emitting started/completed/failed events.
"""

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional, Union

from agentic_inquiry.correlation import correlation_context
from agentic_inquiry.events.models import EventStatus

if TYPE_CHECKING:
    from agentic_inquiry.events.system import EventSystem

logger = logging.getLogger(__name__)


class NoOpOperationTracker:
    """No-op operation tracker for when event system is not available.

    Provides the same interface as OperationTracker but does nothing.
    """

    async def progress(self, **metadata: Any) -> None:
        """No-op progress update."""
        pass

    async def complete(self, **metadata: Any) -> None:
        """No-op completion."""
        pass

    async def fail(self, error: str, **metadata: Any) -> None:
        """No-op failure."""
        pass


class OperationTracker:
    """Tracks an operation lifecycle with automatic event emission.
    
    This class provides methods to emit progress, completion, and failure events
    for a tracked operation. It's typically used via the track_operation context
    manager rather than instantiated directly.
    
    Example:
        >>> async with track_operation(events, "indexing", "pipeline") as op:
        ...     await op.progress(files_processed=10)
        ...     # Automatically emits completed on success
    """
    
    def __init__(
        self,
        event_system: "EventSystem",
        operation_type: str,
        source: str,
        operation_id: str,
    ):
        """Initialize operation tracker.
        
        Args:
            event_system: EventSystem instance for emitting events
            operation_type: Base event type (e.g., "indexing")
            source: Source component name
            operation_id: Operation ID (typically correlation ID)
        """
        self.event_system = event_system
        self.operation_type = operation_type
        self.source = source
        self.operation_id = operation_id
    
    async def progress(self, **metadata: Any) -> None:
        """Emit progress event.
        
        Args:
            **metadata: Progress metadata (e.g., files_processed=10)
        """
        await self.event_system.emit(
            f"{self.operation_type}.progress",
            source=self.source,
            status=EventStatus.PROGRESS,
            operation_id=self.operation_id,
            **metadata,
        )
    
    async def complete(self, **metadata: Any) -> None:
        """Emit completion event.
        
        Args:
            **metadata: Completion metadata (e.g., total_files=42)
        """
        await self.event_system.emit(
            f"{self.operation_type}.completed",
            source=self.source,
            status=EventStatus.COMPLETED,
            operation_id=self.operation_id,
            **metadata,
        )
    
    async def fail(self, error: str, **metadata: Any) -> None:
        """Emit failure event.
        
        Args:
            error: Error message describing the failure
            **metadata: Additional metadata (e.g., error_code=500)
        """
        await self.event_system.emit(
            f"{self.operation_type}.failed",
            source=self.source,
            status=EventStatus.FAILED,
            operation_id=self.operation_id,
            error=error,
            **metadata,
        )


@asynccontextmanager
async def track_operation(
    event_system: Optional["EventSystem"],
    operation_type: str,
    source: str,
    operation_id: Optional[str] = None,
    **start_metadata: Any,
) -> AsyncIterator[Union[OperationTracker, NoOpOperationTracker]]:
    """Context manager for tracking operation lifecycle.

    Automatically emits started/completed/failed events and integrates with
    the correlation ID system for automatic operation grouping.

    If event_system is None, yields a NoOpOperationTracker that does nothing.

    Args:
        event_system: Optional EventSystem instance for emitting events.
                      If None, no events are emitted but the context manager still works.
        operation_type: Base event type (e.g., "indexing")
        source: Source component name
        operation_id: Optional operation ID (uses existing correlation ID if None)
        **start_metadata: Metadata for started event (e.g., file_path="/path/to/file")

    Yields:
        OperationTracker for progress updates (or NoOpOperationTracker if no event system)

    Example:
        >>> async with track_operation(events, "indexing", "pipeline") as op:
        ...     await op.progress(files_processed=10)
        ...     # Automatically emits completed on success
        ...     # Automatically emits failed on exception
    """
    # If no event system, yield a no-op tracker
    if event_system is None:
        yield NoOpOperationTracker()
        return

    from agentic_inquiry.correlation import get_correlation_id

    # If no operation_id provided, use existing correlation ID or generate new one
    if operation_id is None:
        operation_id = get_correlation_id()

    with correlation_context(operation_id) as corr_id:
        # Emit started event
        await event_system.emit(
            f"{operation_type}.started",
            source=source,
            status=EventStatus.STARTED,
            operation_id=corr_id,
            **start_metadata,
        )

        tracker = OperationTracker(event_system, operation_type, source, corr_id)

        try:
            yield tracker
            # Emit completed event on success
            await tracker.complete()
        except Exception as e:
            # Emit failed event on exception
            await tracker.fail(str(e))
            raise
