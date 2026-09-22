"""SQLite storage providers package.

This package provides SQLite implementations of storage protocols:
    - SQLiteEventProvider: Event storage using SQLite
    - SQLiteFileTrackerProvider: File tracker using SQLite

These providers wrap existing implementations (SQLiteEventStorage, FileTracker)
and ensure full protocol compliance.

SQLite is the default backend for local development and single-node deployments.
No additional dependencies required - aiosqlite is a core dependency.

Example:
    >>> from agent_vault.storage.providers.sqlite import (
    ...     SQLiteEventProvider,
    ...     SQLiteFileTrackerProvider,
    ... )
    >>>
    >>> # Event storage
    >>> events = SQLiteEventProvider(db_path="/path/to/events.db", project_id="myproj")
    >>> await events.initialize()
    >>> await events.write_events([event1, event2])
    >>>
    >>> # File tracking
    >>> tracker = SQLiteFileTrackerProvider(db_path="/path/to/tracker.db", project_id="myproj")
    >>> await tracker.initialize()
    >>> if await tracker.has_changed("/path/to/file.py"):
    ...     await process_and_update(tracker, "/path/to/file.py")
"""

from agent_vault.storage.providers.sqlite.events import SQLiteEventProvider
from agent_vault.storage.providers.sqlite.file_tracker import (
    SQLiteFileTrackerProvider,
)

__all__ = [
    "SQLiteEventProvider",
    "SQLiteFileTrackerProvider",
]
