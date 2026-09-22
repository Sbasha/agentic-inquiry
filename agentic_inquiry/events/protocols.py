"""Protocol definitions for event storage backends.

This module defines protocols for event persistence, enabling backend
swappability without modifying event system implementations.

Design reference: DES-S2-003 in .sessions/deep-architecture-review/009-design.md
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentic_inquiry.events.models import Event


@runtime_checkable
class EventStorageBackend(Protocol):
    """Protocol for event persistence backends.

    This protocol defines the minimal interface required for event storage.
    Implementations can provide additional methods, but consumers should
    depend only on this interface for maximum flexibility.

    Example implementation:
        class SQLiteEventStorage:
            async def initialize(self) -> None:
                await self._ensure_schema()

            async def write_events(self, events: List[Event]) -> int:
                # Insert events into SQLite
                await self._conn.executemany(...)
                return len(events)

            async def query_events(
                self,
                event_type: Optional[str] = None,
                since: Optional[datetime] = None,
                until: Optional[datetime] = None,
                limit: int = 100,
            ) -> List[Event]:
                # Build and execute query
                return [self._row_to_event(row) for row in rows]

            async def delete_before(self, cutoff: datetime) -> int:
                # Delete old events
                return deleted_count

            async def close(self) -> None:
                await self._conn.close()
    """

    async def initialize(self) -> None:
        """Initialize the storage backend.

        This method should be idempotent - calling it multiple times
        should have the same effect as calling it once.

        Implementations should:
        - Create database schemas/tables if needed
        - Establish connections
        - Set up any required indexes
        """
        ...

    async def write_events(
        self,
        events: List["Event"],
    ) -> int:
        """Write a batch of events to storage.

        Args:
            events: List of Event objects to persist

        Returns:
            Number of events successfully written

        Note:
            Implementations should handle duplicate event_ids gracefully
            (either skip or update).
        """
        ...

    async def query_events(
        self,
        event_type: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 100,
    ) -> List["Event"]:
        """Query events with optional filters.

        Args:
            event_type: Filter by event type (e.g., "indexing.started")
            since: Return events after this timestamp (exclusive)
            until: Return events before this timestamp (inclusive)
            limit: Maximum number of events to return

        Returns:
            List of matching events, ordered by timestamp descending
        """
        ...

    async def delete_before(
        self,
        cutoff: datetime,
    ) -> int:
        """Delete events before the cutoff timestamp.

        Used for implementing retention policies.

        Args:
            cutoff: Delete all events with timestamp before this

        Returns:
            Number of events deleted
        """
        ...

    async def close(self) -> None:
        """Close storage connections and release resources.

        This method should be safe to call multiple times.
        """
        ...


@runtime_checkable
class EventStorageQueryCapability(Protocol):
    """Extended query capability for event storage.

    This protocol defines additional query methods that some backends
    may support for more advanced use cases.
    """

    async def get_operation_events(
        self,
        operation_id: str,
        project_id: Optional[str] = None,
    ) -> List["Event"]:
        """Get all events for a specific operation.

        Args:
            operation_id: Operation ID to query
            project_id: Optional project filter

        Returns:
            List of events for the operation, ordered by timestamp
        """
        ...

    async def get_operation_status(
        self,
        operation_id: str,
        project_id: Optional[str] = None,
    ) -> dict:
        """Get aggregated status for an operation.

        Args:
            operation_id: Operation ID to query
            project_id: Optional project filter

        Returns:
            Dictionary with status summary including:
            - start_time, end_time
            - event_count, error_count
            - current status
            - duration
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
            project_id: Optional project filter
            event_type: Optional event type filter
            since: Count events after this timestamp
            until: Count events before this timestamp

        Returns:
            Number of matching events
        """
        ...


@runtime_checkable
class EventStorageMaintenanceCapability(Protocol):
    """Maintenance capability for event storage.

    This protocol defines maintenance operations that may be
    supported by some storage backends.
    """

    async def vacuum(self) -> None:
        """Compact storage to reclaim unused space.

        This operation may require exclusive access and should
        typically be run during maintenance windows.
        """
        ...


def has_query_capability(backend: EventStorageBackend) -> bool:
    """Check if backend supports extended query operations.

    Args:
        backend: Event storage backend to check

    Returns:
        True if backend implements EventStorageQueryCapability
    """
    return isinstance(backend, EventStorageQueryCapability)


def has_maintenance_capability(backend: EventStorageBackend) -> bool:
    """Check if backend supports maintenance operations.

    Args:
        backend: Event storage backend to check

    Returns:
        True if backend implements EventStorageMaintenanceCapability
    """
    return isinstance(backend, EventStorageMaintenanceCapability)
