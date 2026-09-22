"""Protocols for relational database adapters (EventStore, FileTracker).

This module defines the protocol interfaces for relational database adapters
used for event storage and file tracking. These protocols enable testing
and alternative implementations while maintaining a consistent API.

Design principles:
- Public initialize()/close() lifecycle
- No private _ensure_initialized or _init_database in protocol
- Async-only API for consistency
- Type-safe method signatures
"""

from typing import TYPE_CHECKING, List, Optional, Protocol, Tuple, runtime_checkable

if TYPE_CHECKING:
    from agentic_inquiry.events.models import Event, EventStatus


@runtime_checkable
class EventStoreProtocol(Protocol):
    """Protocol for event storage adapters.

    This protocol defines the interface for storing and querying events
    in a persistent storage backend. Implementations must handle:
    - Event persistence with project isolation
    - Efficient querying by operation, type, and time range
    - Automatic cleanup of old events
    - Safe concurrent access

    Lifecycle:
        1. Create instance with __init__
        2. Call initialize() to set up database
        3. Use store/query methods
        4. Call close() when done

    Example:
        store = SQLiteEventStore(db_path="events.db", project_id="my_project")
        await store.initialize()

        await store.store_events([event1, event2])
        events = await store.get_operation_events("op_123")

        await store.close()
    """

    # --- Properties ---

    @property
    def project_id(self) -> str:
        """Project identifier for data isolation."""
        ...

    @property
    def db_path(self) -> str:
        """Path to database file."""
        ...

    # --- Lifecycle ---

    async def initialize(self) -> None:
        """Initialize the event store.

        This method sets up the database schema and connections. It must be
        safe to call multiple times (idempotent). Subsequent calls should
        be no-ops.

        This is the public initialization method. Implementations may use
        internal helpers, but this is the required entry point.

        Raises:
            IOError: If database initialization fails
            PermissionError: If unable to create/access database file
        """
        ...

    async def close(self) -> None:
        """Close database connections and clean up resources.

        This method should:
        - Commit any pending transactions
        - Close database connections
        - Release file locks
        - Be safe to call multiple times (idempotent)

        After calling close(), the store should not be used unless
        initialize() is called again.
        """
        ...

    # --- Write Operations ---

    async def store_events(self, events: List["Event"]) -> None:
        """Store multiple events (batch operation).

        Events are persisted with their full metadata including:
        - event_id (unique identifier)
        - project_id (for isolation)
        - operation_id (for grouping)
        - timestamp (for ordering)
        - event_type (for filtering)
        - status (completed/failed/in_progress)
        - source (component that emitted event)
        - metadata (additional context)

        Args:
            events: List of events to store

        Note:
            This method should not raise on integrity errors (duplicate IDs).
            Duplicates should be logged and skipped to avoid breaking callers.
        """
        ...

    # --- Read Operations ---

    async def get_operation_events(
        self,
        operation_id: str,
        project_id: Optional[str] = None,
    ) -> List["Event"]:
        """Get all events for an operation.

        Returns events ordered by timestamp (ascending), allowing replay
        of operation history.

        Args:
            operation_id: Operation ID to query
            project_id: Optional project ID filter (defaults to self.project_id)

        Returns:
            List of events ordered by timestamp (oldest first)
        """
        ...

    async def get_events_by_type(
        self,
        event_type: str,
        project_id: Optional[str] = None,
        limit: int = 1000,
    ) -> List["Event"]:
        """Get events filtered by event type.

        Args:
            event_type: Event type to filter by (e.g., "indexing.started")
            project_id: Optional project ID filter (defaults to self.project_id)
            limit: Maximum number of events to return (default: 1000)

        Returns:
            List of events ordered by timestamp descending (newest first)
        """
        ...

    async def get_events_by_time_range(
        self,
        start_time: float,
        end_time: float,
        project_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 1000,
    ) -> List["Event"]:
        """Get events within a timestamp range.

        Args:
            start_time: Start timestamp (Unix timestamp with microseconds)
            end_time: End timestamp (Unix timestamp with microseconds)
            project_id: Optional project ID filter (defaults to self.project_id)
            event_type: Optional event type filter
            limit: Maximum number of events to return (default: 1000)

        Returns:
            List of events ordered by timestamp ascending (oldest first)
        """
        ...

    async def get_latest_events(
        self,
        limit: int = 100,
        project_id: Optional[str] = None,
        status: Optional["EventStatus"] = None,
    ) -> List["Event"]:
        """Get the latest N events.

        Useful for monitoring recent activity or debugging.

        Args:
            limit: Maximum number of events to return (default: 100)
            project_id: Optional project ID filter (defaults to self.project_id)
            status: Optional status filter (e.g., EventStatus.FAILED)

        Returns:
            List of events ordered by timestamp descending (newest first)
        """
        ...

    async def get_operation_status(
        self,
        operation_id: str,
        project_id: Optional[str] = None,
    ) -> dict:
        """Get operation status summary.

        Provides aggregated statistics about an operation's execution.

        Args:
            operation_id: Operation ID to query
            project_id: Optional project ID filter (defaults to self.project_id)

        Returns:
            Dictionary with:
                - operation_id: The operation ID
                - project_id: The project ID
                - start_time: Timestamp of first event (or None)
                - end_time: Timestamp of last event (or None)
                - event_count: Total number of events
                - error_count: Number of failed events
                - status: Most recent event status (or None)
                - duration: Time between first and last event in seconds (or None)
        """
        ...

    async def count_events(
        self,
        project_id: Optional[str] = None,
        event_type: Optional[str] = None,
        status: Optional["EventStatus"] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> int:
        """Count events matching filters.

        Useful for pagination and monitoring.

        Args:
            project_id: Optional project ID filter (defaults to self.project_id)
            event_type: Optional event type filter
            status: Optional status filter
            start_time: Optional start timestamp filter
            end_time: Optional end timestamp filter

        Returns:
            Count of matching events
        """
        ...

    # --- Maintenance ---

    async def cleanup_old_events(
        self,
        retention_days: int,
        project_id: Optional[str] = None,
    ) -> int:
        """Delete events older than retention period.

        This method removes events older than the specified number of days
        and performs any necessary cleanup (e.g., WAL checkpoint).

        Args:
            retention_days: Number of days to retain events (events older
                than this are deleted)
            project_id: Optional project ID filter (defaults to self.project_id).
                If None, cleans up events for the current project only.

        Returns:
            Count of deleted events

        Raises:
            ValueError: If retention_days <= 0
        """
        ...

    async def vacuum(self) -> None:
        """Compact the database to reclaim unused space.

        This is a maintenance operation that rebuilds the database file
        to eliminate fragmentation and reclaim space from deleted records.

        Note:
            - May take significant time for large databases
            - Requires exclusive database access
            - Requires temporary disk space equal to database size
            - Should be run during maintenance windows
        """
        ...


@runtime_checkable
class FileTrackerProtocol(Protocol):
    """Protocol for file state tracking adapters.

    This protocol defines the interface for tracking file states using
    content hashes for change detection. Implementations must handle:
    - Hash-based change detection (not modification time)
    - Project isolation
    - Efficient hash storage and retrieval
    - Safe concurrent access

    Lifecycle:
        1. Create instance with __init__
        2. Call initialize() to set up database
        3. Use hash tracking methods
        4. Call close() when done

    Example:
        tracker = SQLiteFileTracker(db_path="files.db", project_id="my_project")
        await tracker.initialize()

        # Check if file changed
        if await tracker.has_changed("/path/to/file.py"):
            # Re-process file
            await process_file("/path/to/file.py")
            # Update hash
            await tracker.update_hash("/path/to/file.py")

        await tracker.close()
    """

    # --- Properties ---

    @property
    def project_id(self) -> str:
        """Project identifier for data isolation."""
        ...

    @property
    def db_path(self) -> str:
        """Path to database file."""
        ...

    # --- Lifecycle ---

    async def initialize(self) -> None:
        """Initialize the file tracker database.

        This method sets up the database schema. It must be safe to call
        multiple times (idempotent). Subsequent calls should be no-ops.

        This is the public initialization method. Implementations may use
        internal helpers, but this is the required entry point.

        Raises:
            IOError: If database initialization fails
            PermissionError: If unable to create/access database file
        """
        ...

    def close(self) -> None:
        """Close database connections.

        Note: This is synchronous for backward compatibility with
        watchdog callbacks. Implementations using persistent connections
        should clean up resources here.

        This method should be safe to call multiple times (idempotent).
        """
        ...

    # --- Hash Operations ---

    async def get_hash(self, file_path: str) -> Optional[str]:
        """Get stored hash for a file in the current project.

        Args:
            file_path: Path to the file

        Returns:
            Stored hash string (e.g., SHA256 hex), or None if file not
            tracked in current project
        """
        ...

    async def update_hash(
        self,
        file_path: str,
        content_hash: Optional[str] = None,
    ) -> str:
        """Update or insert hash for a file in the current project.

        If content_hash is not provided, it should be computed from the file.
        Uses upsert semantics: insert if new, update if exists.

        Args:
            file_path: Path to the file
            content_hash: Optional pre-computed hash. If None, compute from file.

        Returns:
            The hash that was stored

        Raises:
            FileNotFoundError: If file doesn't exist and hash not provided
            IOError: If file cannot be read
        """
        ...

    async def has_changed(self, file_path: str) -> bool:
        """Check if file has changed since last tracking.

        Compares current file hash with stored hash.

        Args:
            file_path: Path to the file

        Returns:
            True if file has changed or is not tracked, False otherwise

        Note:
            If file doesn't exist or can't be read, returns True (conservative
            behavior assumes change).
        """
        ...

    async def remove_file(self, file_path: str) -> bool:
        """Remove a file from tracking in the current project.

        Args:
            file_path: Path to the file

        Returns:
            True if file was tracked and removed, False if not tracked
            in current project
        """
        ...

    async def list_tracked_files(self) -> List[Tuple[str, str]]:
        """List all tracked files and their hashes in the current project.

        Returns:
            List of (file_path, content_hash) tuples for current project
        """
        ...

    async def clear(self) -> None:
        """Clear all tracked files from the current project.

        Note: This only clears files for the current project_id,
        not all projects in the database.
        """
        ...

    # --- Synchronous Wrappers (for watchdog compatibility) ---

    def update_hash_sync(
        self,
        file_path: str,
        content_hash: Optional[str] = None,
    ) -> str:
        """Synchronous wrapper for update_hash.

        This method runs the async update_hash in a new event loop.
        Use when calling from synchronous code (e.g., watchdog callbacks).

        Args:
            file_path: Path to the file
            content_hash: Optional pre-computed hash

        Returns:
            The hash that was stored
        """
        ...

    def has_changed_sync(self, file_path: str) -> bool:
        """Synchronous wrapper for has_changed.

        This method runs the async has_changed in a new event loop.
        Use when calling from synchronous code (e.g., watchdog callbacks).

        Args:
            file_path: Path to the file

        Returns:
            True if file has changed or is not tracked, False otherwise
        """
        ...

    def remove_file_sync(self, file_path: str) -> bool:
        """Synchronous wrapper for remove_file.

        This method runs the async remove_file in a new event loop.
        Use when calling from synchronous code (e.g., watchdog callbacks).

        Args:
            file_path: Path to the file

        Returns:
            True if file was tracked and removed, False if not tracked
        """
        ...
