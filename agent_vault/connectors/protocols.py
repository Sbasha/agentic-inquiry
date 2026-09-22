"""Connector protocols.

Defines the protocol interfaces for content connectors:
- ConnectorProtocol: Core enumeration and retrieval
- WatchCapability: Real-time change monitoring
- AuthCapability: Authentication lifecycle
- ChangeDetectionCapability: Item-level change detection
- HashTrackerProtocol: Hash-based content tracking for deduplication

All protocols are @runtime_checkable for isinstance() detection.

See: docs/design/connector-architecture.md
"""
from __future__ import annotations

from enum import Enum
from typing import AsyncIterator, Protocol, runtime_checkable

from agent_vault.connectors.types import SourceContent, SourceItem


class WatchEventType(Enum):
    """Types of file system events.

    Used by WatchCapability to indicate what kind of change occurred.
    """

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    MOVED = "moved"


@runtime_checkable
class ConnectorProtocol(Protocol):
    """Protocol for content source connectors.

    Connectors abstract different content sources (filesystem, S3, GitHub, etc.)
    into a consistent interface for enumeration and retrieval.

    All methods are async to support both local and remote backends.

    Required Methods:
        list: Enumerate content items under a root path.
        open: Retrieve content for a specific item.

    Lifecycle:
        Connectors may require initialization (e.g., authentication).
        Use initialize() if provided, or rely on lazy initialization.

    Example:
        >>> connector = FileSystemConnector()
        >>> async for item in connector.list("/path/to/project"):
        ...     if item.content_type == "text/x-python":
        ...         content = await connector.open(item)
        ...         process(content.text)
    """

    def list(self, root: str) -> AsyncIterator[SourceItem]:
        """Enumerate content items under a root path.

        Yields SourceItem objects for each discoverable content unit.
        Implementation should handle ignore patterns and filtering.

        Args:
            root: Root path or URI to enumerate.
                - Filesystem: absolute or relative path
                - S3: bucket/prefix
                - GitHub: repo path

        Yields:
            SourceItem for each discovered content unit.

        Raises:
            FileNotFoundError: If root does not exist.
            PermissionError: If access is denied.
        """
        ...

    async def open(self, item: SourceItem) -> SourceContent:
        """Retrieve content for a source item.

        Fetches the actual content data for a previously enumerated item.

        Args:
            item: SourceItem from list() to retrieve.

        Returns:
            SourceContent with data and metadata.

        Raises:
            FileNotFoundError: If item no longer exists.
            PermissionError: If access is denied.
        """
        ...


@runtime_checkable
class WatchCapability(Protocol):
    """Protocol for connectors that support real-time change monitoring.

    Enables incremental indexing by watching for file changes.
    Not all connectors support this capability.

    Detection:
        if isinstance(connector, WatchCapability):
            async for event_type, item in connector.watch(root):
                handle_change(event_type, item)
    """

    def watch(
        self, root: str
    ) -> AsyncIterator[tuple[WatchEventType, SourceItem]]:
        """Watch for changes under a root path.

        Yields (event_type, item) tuples as changes occur.
        This is a long-running async generator that should be cancelled
        when watching is no longer needed.

        Args:
            root: Root path to watch.

        Yields:
            Tuple of (WatchEventType, SourceItem) for each change.
        """
        ...


@runtime_checkable
class AuthCapability(Protocol):
    """Protocol for connectors that require authentication.

    Provides authentication lifecycle management for connectors
    that access protected resources (S3, GitHub, etc.).

    Detection:
        if isinstance(connector, AuthCapability):
            await connector.authenticate()
    """

    async def authenticate(self) -> None:
        """Perform initial authentication.

        Should be called before using the connector if authentication
        is required. May be a no-op if already authenticated.

        Raises:
            AuthenticationError: If authentication fails.
        """
        ...

    async def refresh_auth(self) -> None:
        """Refresh authentication credentials.

        Called when credentials may have expired. Should refresh
        tokens or re-authenticate as needed.

        Raises:
            AuthenticationError: If refresh fails.
        """
        ...

    @property
    def is_authenticated(self) -> bool:
        """Check if currently authenticated.

        Returns:
            True if authentication is valid.
        """
        ...


@runtime_checkable
class ChangeDetectionCapability(Protocol):
    """Protocol for connectors that support change detection.

    Enables efficient incremental processing by detecting
    which items have changed since last processing.
    """

    async def has_changed(self, item: SourceItem) -> bool:
        """Check if an item has changed since last processing.

        Uses content_hash or modified_at for comparison.

        Args:
            item: SourceItem to check.

        Returns:
            True if item has changed or is new.
        """
        ...

    async def mark_processed(self, item: SourceItem) -> None:
        """Mark an item as processed.

        Records the current state (hash/timestamp) for future
        change detection comparisons.

        Args:
            item: SourceItem that was processed.
        """
        ...


@runtime_checkable
class HashTrackerProtocol(Protocol):
    """Protocol for tracking processed files by content hash.

    Provides a low-level interface for tracking which file hashes have been
    processed. Used for deduplication across different URIs with the same content
    and for incremental processing.

    This is distinct from ChangeDetectionCapability which operates on SourceItem
    objects with URIs. HashTrackerProtocol operates purely on content hashes.

    Detection:
        if isinstance(tracker, HashTrackerProtocol):
            if await tracker.is_processed(content_hash):
                # Skip already-processed content
                continue

    Example:
        >>> tracker = MyHashTracker()
        >>> if not await tracker.is_processed(file_hash):
        ...     process_file(file_path)
        ...     await tracker.mark_processed(file_hash)
    """

    async def is_processed(self, file_hash: str) -> bool:
        """Check if a file hash has been processed.

        Args:
            file_hash: Content hash (e.g., SHA256) to check.

        Returns:
            True if the hash has been marked as processed.
        """
        ...

    async def mark_processed(self, file_hash: str) -> None:
        """Mark a file hash as processed.

        Records that content with this hash has been processed.
        Subsequent calls to is_processed() should return True.

        Args:
            file_hash: Content hash (e.g., SHA256) to mark.
        """
        ...

    async def get_processed_count(self) -> int:
        """Get the count of processed file hashes.

        Returns:
            Number of unique hashes marked as processed.
        """
        ...

    async def clear(self) -> int:
        """Clear all tracking data.

        Removes all processed hash records.

        Returns:
            Number of entries cleared.
        """
        ...


# Type aliases for clarity
WatchEvent = tuple[WatchEventType, SourceItem]


def has_watch_capability(connector: ConnectorProtocol) -> bool:
    """Check if connector supports file watching.

    Args:
        connector: Connector to check.

    Returns:
        True if connector implements WatchCapability.
    """
    return isinstance(connector, WatchCapability)


def has_auth_capability(connector: ConnectorProtocol) -> bool:
    """Check if connector requires authentication.

    Args:
        connector: Connector to check.

    Returns:
        True if connector implements AuthCapability.
    """
    return isinstance(connector, AuthCapability)


def has_change_detection(connector: ConnectorProtocol) -> bool:
    """Check if connector supports change detection.

    Args:
        connector: Connector to check.

    Returns:
        True if connector implements ChangeDetectionCapability.
    """
    return isinstance(connector, ChangeDetectionCapability)


def has_hash_tracker(tracker: object) -> bool:
    """Check if an object implements the HashTrackerProtocol.

    Args:
        tracker: Object to check.

    Returns:
        True if object implements HashTrackerProtocol.
    """
    return isinstance(tracker, HashTrackerProtocol)
