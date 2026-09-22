"""File tracker protocol for file state tracking abstraction.

This module defines the protocol that all file tracker providers must implement.
It provides the methods needed by FileWatcher and related file monitoring components.

Protocols defined:
    - FileTrackerProtocol: Methods for file hash tracking and change detection

Design principles:
    - Minimal surface area: Only methods needed for file state tracking
    - Capability-based: Check capabilities at runtime with isinstance()
    - Dual interface: Async methods + sync wrappers for watchdog callbacks
    - Hash-based: Uses content hashes for change detection (not mtime)

Implementations:
    - SQLiteFileTracker: SQLite-based file tracking
    - PostgresFileTracker: PostgreSQL-based tracking (future)
    - AlloyDBFileTracker: GCP AlloyDB tracking (future)

Note:
    This protocol uses sync wrappers for compatibility with watchdog's
    synchronous callback model. See user decision Q7=B in design docs.
"""

from __future__ import annotations

from typing import (
    Any,
    List,
    Optional,
    Protocol,
    Tuple,
    runtime_checkable,
)


@runtime_checkable
class FileTrackerProtocol(Protocol):
    """Protocol for file state tracking operations.

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
        >>> tracker: FileTrackerProtocol = SQLiteFileTracker(db_path, project_id)
        >>> await tracker.initialize()
        >>>
        >>> # Check if file changed
        >>> if await tracker.has_changed("/path/to/file.py"):
        ...     await process_file("/path/to/file.py")
        ...     await tracker.update_hash("/path/to/file.py")
        >>>
        >>> await tracker.close()
    """

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def project_id(self) -> str:
        """Project identifier for data isolation."""
        ...

    @property
    def db_path(self) -> str:
        """Path to database file."""
        ...

    # =========================================================================
    # Lifecycle Operations
    # =========================================================================

    async def initialize(self) -> None:
        """Initialize the file tracker database.

        This method sets up the database schema. It must be safe to call
        multiple times (idempotent). Subsequent calls should be no-ops.

        Raises:
            IOError: If database initialization fails
            PermissionError: If unable to create/access database file
        """
        ...

    async def close(self) -> None:
        """Close database connections.

        Note: This is async for consistency with other storage protocols.
        Implementations should clean up resources here.

        This method should be safe to call multiple times (idempotent).
        """
        ...

    # =========================================================================
    # Hash Operations (Async)
    # =========================================================================

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

    # =========================================================================
    # Synchronous Wrappers (for watchdog compatibility)
    # =========================================================================

    def get_hash_sync(self, file_path: str) -> Optional[str]:
        """Synchronous wrapper for get_hash.

        This method runs the async get_hash in a new event loop.
        Use when calling from synchronous code (e.g., watchdog callbacks).

        Args:
            file_path: Path to the file

        Returns:
            Stored hash string, or None if file not tracked
        """
        ...

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


def has_file_tracker(obj: Any) -> bool:
    """Check if an object implements FileTrackerProtocol.

    Uses runtime_checkable protocol for structural type checking.

    Args:
        obj: Object to check

    Returns:
        True if obj implements FileTrackerProtocol

    Example:
        >>> if has_file_tracker(tracker):
        ...     changed = await tracker.has_changed("/path/to/file.py")
    """
    return isinstance(obj, FileTrackerProtocol)
