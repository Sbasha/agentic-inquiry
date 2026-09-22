"""Event storage protocol for event persistence abstraction.

This module defines the protocol that all event storage providers must implement.
It provides the methods needed by EventSystem and related event tracking components.

Protocols defined:
    - EventStorageProtocol: Methods for event persistence and querying

Design principles:
    - Minimal surface area: Only methods needed for event operations
    - Capability-based: Check capabilities at runtime with isinstance()
    - Domain types: Uses Event from agentic_inquiry.events.models
    - Async-only: All I/O operations are async

Implementations:
    - SQLiteEventStorage: SQLite-based event storage
    - PostgresEventStorage: PostgreSQL-based event storage (future)
"""

from __future__ import annotations

from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    runtime_checkable,
)

if TYPE_CHECKING:
    from agentic_inquiry.events.models import Event


@runtime_checkable
class EventStorageProtocol(Protocol):
    """Protocol for event storage operations.

    This protocol defines the methods needed by EventSystem and related
    components for event persistence, querying, and lifecycle management.

    Methods use the Event domain type from agentic_inquiry.events.models
    for type safety and consistency.

    Implementations:
        - SQLiteEventStorage: File-based SQLite storage
        - PostgresEventStorage: PostgreSQL backend (future)
        - AlloyDBEventStorage: GCP AlloyDB backend (future)

    Example:
        >>> storage: EventStorageProtocol = SQLiteEventStorage(db_path, project_id)
        >>> await storage.initialize()
        >>> count = await storage.write_events([event1, event2])
        >>> events = await storage.query_events(event_type="indexing.complete")
        >>> status = await storage.get_operation_status("op-123")
    """

    # =========================================================================
    # Lifecycle Operations
    # =========================================================================

    async def initialize(self) -> None:
        """Initialize storage and create schema if needed.

        Must be called before any other operations. Implementations should
        be idempotent - calling initialize() multiple times is safe.

        Raises:
            RuntimeError: If initialization fails
        """
        ...

    async def close(self) -> None:
        """Close storage connections and release resources.

        Should be called when the storage is no longer needed.
        After close(), no other methods should be called.

        Raises:
            RuntimeError: If close fails
        """
        ...

    # =========================================================================
    # Write Operations
    # =========================================================================

    async def write_events(
        self,
        events: List["Event"],
    ) -> int:
        """Write a batch of events to storage.

        Batch writes events for efficient bulk inserts. Events are written
        atomically - either all succeed or none are persisted.

        Args:
            events: List of Event objects to persist

        Returns:
            Number of events successfully written

        Raises:
            RuntimeError: If storage not initialized
        """
        ...

    # =========================================================================
    # Query Operations
    # =========================================================================

    async def query_events(
        self,
        event_type: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 100,
    ) -> List["Event"]:
        """Query events with optional filters.

        Returns events matching the filter criteria, ordered by timestamp
        descending (most recent first).

        Args:
            event_type: Filter by event type (e.g., "indexing.started")
            since: Return events after this timestamp (exclusive)
            until: Return events before this timestamp (inclusive)
            limit: Maximum number of events to return (default: 100)

        Returns:
            List of matching events, ordered by timestamp descending

        Raises:
            RuntimeError: If storage not initialized
        """
        ...

    async def get_operation_events(
        self,
        operation_id: str,
        project_id: Optional[str] = None,
    ) -> List["Event"]:
        """Get all events for a specific operation.

        Returns all events associated with the given operation ID,
        ordered by timestamp ascending (chronological order).

        Args:
            operation_id: Operation ID to query
            project_id: Optional project filter (defaults to current project)

        Returns:
            List of events ordered by timestamp ascending

        Raises:
            RuntimeError: If storage not initialized
        """
        ...

    async def get_operation_status(
        self,
        operation_id: str,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get aggregated status for an operation.

        Returns summary statistics for all events associated with
        the given operation, including timing and error counts.

        Args:
            operation_id: Operation ID to query
            project_id: Optional project filter (defaults to current project)

        Returns:
            Dictionary with status summary containing:
                - operation_id: The operation ID
                - project_id: The project ID
                - start_time: Timestamp of first event (or None)
                - end_time: Timestamp of last event (or None)
                - event_count: Total number of events
                - error_count: Number of failed events
                - status: Most recent event status
                - duration: Time between first and last event (or None)

        Raises:
            RuntimeError: If storage not initialized
        """
        ...

    async def count_events(
        self,
        project_id: Optional[str] = None,
        event_type: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> int:
        """Count events matching filters.

        Args:
            project_id: Optional project filter (defaults to current project)
            event_type: Optional event type filter
            since: Count events after this timestamp
            until: Count events before this timestamp

        Returns:
            Number of matching events

        Raises:
            RuntimeError: If storage not initialized
        """
        ...

    # =========================================================================
    # Maintenance Operations
    # =========================================================================

    async def delete_before(
        self,
        cutoff: datetime,
    ) -> int:
        """Delete events before the cutoff timestamp.

        Used for retention policy enforcement. Deletes all events with
        timestamps strictly before the cutoff.

        Args:
            cutoff: Delete all events with timestamp before this

        Returns:
            Number of events deleted

        Raises:
            RuntimeError: If storage not initialized or operation fails
        """
        ...

    async def run_maintenance(self) -> Dict[str, Any]:
        """Run storage maintenance operations.

        Performs backend-specific optimization tasks such as:
        - SQLite: VACUUM, WAL checkpoint
        - PostgreSQL: VACUUM ANALYZE, reindex
        - AlloyDB: Similar to PostgreSQL

        Should be called periodically or after large batch deletions.

        Returns:
            Dict with maintenance results including summary stats

        Raises:
            RuntimeError: If storage not initialized or maintenance fails
        """
        ...


def has_event_storage(obj: Any) -> bool:
    """Check if an object implements EventStorageProtocol.

    Uses runtime_checkable protocol for structural type checking.

    Args:
        obj: Object to check

    Returns:
        True if obj implements EventStorageProtocol

    Example:
        >>> if has_event_storage(storage):
        ...     await storage.write_events(events)
    """
    return isinstance(obj, EventStorageProtocol)
