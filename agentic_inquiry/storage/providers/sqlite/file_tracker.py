"""SQLite file tracker storage provider.

This module provides a protocol-compliant SQLite file tracker provider
by extending the existing FileTracker with missing protocol methods.

Design reference: Phase 4 GCP Connectors implementation plan
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from agentic_inquiry.watching.file_tracker import FileTracker

if TYPE_CHECKING:
    from agentic_inquiry.config import Config

logger = logging.getLogger(__name__)


class SQLiteFileTrackerProvider(FileTracker):
    """SQLite implementation of FileTrackerProtocol.

    This provider extends FileTracker with full protocol compliance,
    adding the async close() and get_hash_sync() methods required
    by FileTrackerProtocol.

    All inherited methods from FileTracker:
        - initialize(): Initialize database and schema
        - get_hash(): Get stored hash for a file
        - update_hash(): Update or insert hash for a file
        - has_changed(): Check if file has changed
        - remove_file(): Remove file from tracking
        - list_tracked_files(): List all tracked files
        - clear(): Clear all tracked files for project
        - update_hash_sync(): Sync wrapper for update_hash
        - has_changed_sync(): Sync wrapper for has_changed
        - remove_file_sync(): Sync wrapper for remove_file

    Added methods:
        - close(): Async close (protocol-compliant)
        - get_hash_sync(): Sync wrapper for get_hash

    Example:
        >>> provider = SQLiteFileTrackerProvider(
        ...     db_path="/path/to/file_tracker.db",
        ...     project_id="my_project",
        ... )
        >>> await provider.initialize()
        >>>
        >>> # Check if file changed
        >>> if await provider.has_changed("/path/to/file.py"):
        ...     await process_file("/path/to/file.py")
        ...     await provider.update_hash("/path/to/file.py")
        >>>
        >>> await provider.close()
    """

    SUPPORTED_ROLES: frozenset[str] = frozenset({"file_tracker"})

    def __init__(
        self,
        config: Optional["Config"] = None,
        project_id: Optional[str] = None,
        db_path: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the SQLite file tracker provider.

        Args:
            config: Optional Config instance. If None, loads default configuration.
            project_id: Project ID for data isolation. If None, uses
                config.storage.default_project_id.
            db_path: Optional path to SQLite database file. If None, uses
                config.storage.get_file_tracker_path().
            **kwargs: Additional configuration (e.g., 'path').
        """
        # Handle 'path' and 'database_path' aliases for 'db_path' from configuration
        if db_path is None:
            db_path = kwargs.get("path") or kwargs.get("database_path")

        super().__init__(config=config, project_id=project_id, db_path=db_path)

    async def close(self) -> None:
        """Close database connections (async version for protocol compliance).

        Note: This is an async wrapper around the sync close() for API
        consistency with other storage protocols. The underlying SQLite
        implementation uses context managers, so this is a no-op.
        """
        # Call parent async close
        await super().close()
        # Small yield to event loop for cleanup
        await asyncio.sleep(0)
        logger.debug(
            "SQLiteFileTrackerProvider closed: project=%s, db=%s",
            self.project_id,
            self.db_path,
        )

    def get_hash_sync(self, file_path: str) -> Optional[str]:
        """Synchronous wrapper for get_hash.

        This method runs the async get_hash in a new event loop.
        Use when calling from synchronous code (e.g., watchdog callbacks).

        Args:
            file_path: Path to the file

        Returns:
            Stored hash string, or None if file not tracked in current project
        """
        return asyncio.run(self.get_hash(file_path))
