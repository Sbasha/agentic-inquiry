"""SQLite implementation of EventStorageBackend.

This module provides a protocol-compliant SQLite adapter for event storage.
It encapsulates all SQLite-specific operations and row conversion logic.

Design reference: DES-S2-003 in .sessions/deep-architecture-review/009-design.md
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import aiosqlite

from agentic_inquiry.events.models import Event, EventStatus
from agentic_inquiry.utils.retry import RetryPolicy

logger = logging.getLogger(__name__)


class SQLiteEventStorage:
    """SQLite implementation of EventStorageBackend protocol.

    This adapter wraps aiosqlite and provides high-level event operations
    that work with Event objects directly.

    The adapter handles:
    - Schema creation and management
    - Row conversion between Event and SQLite format
    - WAL mode for concurrent access
    - Retry logic for database locks
    - Connection management

    Example:
        storage = SQLiteEventStorage(
            db_path="/path/to/events.db",
            project_id="my_project",
        )
        await storage.initialize()
        written = await storage.write_events(events)
        events = await storage.query_events(event_type="indexing.started")
        await storage.close()
    """

    def __init__(
        self,
        db_path: Union[str, Path],
        project_id: str,
    ) -> None:
        """Initialize the SQLite event storage.

        Args:
            db_path: Path to the SQLite database file
            project_id: Project identifier for data isolation
        """
        self._db_path = str(Path(db_path).expanduser().resolve())
        self._project_id = project_id
        self._writer_conn: Optional[aiosqlite.Connection] = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

        # Ensure parent directory exists
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> str:
        """Get the database path."""
        return self._db_path

    @property
    def project_id(self) -> str:
        """Get the project ID."""
        return self._project_id

    async def initialize(self) -> None:
        """Initialize the storage backend.

        Creates database schema, sets up WAL mode, and establishes
        the persistent writer connection. This method is idempotent.
        """
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            await self._init_schema()

            # Create persistent writer connection
            self._writer_conn = await aiosqlite.connect(self._db_path, timeout=5.0)
            self._writer_conn.row_factory = aiosqlite.Row

            # Enable WAL mode for concurrent reads
            await self._writer_conn.execute("PRAGMA journal_mode=WAL")
            await self._writer_conn.execute("PRAGMA synchronous=NORMAL")
            # 10s ``busy_timeout`` was originally sized for
            # ``processing_semaphore_limit=10``; the semaphore is now 20
            # and we've kept the timeout at 10s because in real traffic
            # the writer-queue drains quickly and SQLITE_BUSY hasn't
            # surfaced — but the headroom is tighter. The older 5s
            # ceiling did surface as failed writes under bursty loads
            # under the old 10-worker default. Raise in lockstep if
            # operators push the semaphore well past 20, or sooner if
            # SQLITE_BUSY reports start showing up.
            await self._writer_conn.execute("PRAGMA busy_timeout=10000")
            await self._writer_conn.commit()

            self._initialized = True
            logger.info(
                "SQLiteEventStorage initialized: db=%s, project=%s",
                self._db_path,
                self._project_id,
            )

    async def _init_schema(self) -> None:
        """Initialize database schema."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    operation_id TEXT,
                    session_id TEXT,
                    timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    metadata TEXT,
                    schema_version TEXT NOT NULL DEFAULT '1.0',
                    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_operation_id "
                "ON events(operation_id, timestamp)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_event_type ON events(event_type)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_timestamp ON events(timestamp)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_project_timestamp "
                "ON events(project_id, timestamp)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_status ON events(status)"
            )

            await db.commit()

    async def _retry_on_locked(
        self,
        operation: Any,
        max_retries: int = 3,
    ) -> Any:
        """Retry operation with exponential backoff on lock errors.

        Uses RetryPolicy for consistent retry behavior across the codebase.

        Design reference: S2-005 in .sessions/deep-architecture-review/010-tasks.md

        Args:
            operation: Async callable to retry
            max_retries: Maximum retry attempts

        Returns:
            Result of the operation

        Raises:
            Exception: If all retries exhausted or non-retryable error
        """
        # Create policy for database operations
        policy = RetryPolicy(
            max_attempts=max_retries,
            base_delay=0.1,
            max_delay=2.0,
            exponential_base=2.0,
            jitter=True,  # Prevent lock contention
            jitter_factor=0.3,
            retryable_exceptions=None,  # We handle exceptions manually below
        )

        last_exception: Optional[Exception] = None

        for attempt in range(policy.max_attempts):
            try:
                return await operation()
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e).lower():
                    last_exception = e
                    if attempt < policy.max_attempts - 1:
                        delay = policy.calculate_delay(attempt)
                        logger.warning(
                            "Database locked, retrying in %.2fs (attempt %s/%s)",
                            delay, attempt + 1, policy.max_attempts
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "Database locked after %s attempts", policy.max_attempts
                        )
                        raise
                else:
                    raise
            except sqlite3.IntegrityError as e:
                logger.warning("Integrity constraint violation: %s", e)
                raise
            except sqlite3.DatabaseError as e:
                logger.critical("Database error: %s", e)
                raise

        # Should not reach here, but handle edge case
        if last_exception is not None:
            raise last_exception
        return None  # Should not reach here

    async def write_events(
        self,
        events: List[Event],
    ) -> int:
        """Write a batch of events to storage.

        Args:
            events: List of Event objects to persist

        Returns:
            Number of events successfully written
        """
        if not self._initialized:
            await self.initialize()

        if not events or not self._writer_conn:
            return 0

        async def _do_write() -> None:
            """Inner function for retry logic."""
            await self._writer_conn.executemany(  # type: ignore[union-attr]
                """
                INSERT INTO events (
                    event_id, project_id, operation_id, session_id,
                    timestamp, event_type, status, source, metadata, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [self._event_to_row(event) for event in events],
            )
            await self._writer_conn.commit()  # type: ignore[union-attr]

        try:
            await self._retry_on_locked(_do_write)
            return len(events)
        except sqlite3.IntegrityError:
            logger.warning(
                "Skipping %s events due to integrity constraint", len(events)
            )
            return 0
        except sqlite3.DatabaseError:
            logger.error(
                "Failed to write %s events due to database error", len(events)
            )
            return 0
        except Exception as e:
            logger.error("Failed to write %s events: %s", len(events), e)
            return 0

    async def query_events(
        self,
        event_type: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Event]:
        """Query events with optional filters.

        Args:
            event_type: Filter by event type
            since: Return events after this timestamp (exclusive)
            until: Return events before this timestamp (inclusive)
            limit: Maximum number of events to return

        Returns:
            List of matching events, ordered by timestamp descending
        """
        if not self._initialized:
            await self.initialize()

        conditions = ["project_id = ?"]
        params: List[Any] = [self._project_id]

        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)

        if since is not None:
            conditions.append("timestamp > ?")
            params.append(since.timestamp())

        if until is not None:
            conditions.append("timestamp <= ?")
            params.append(until.timestamp())

        params.append(limit)

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT * FROM events
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT ?
        """

        async with aiosqlite.connect(self._db_path, timeout=2.0) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA query_only=1")

            async with db.execute(query, tuple(params)) as cursor:
                rows = await cursor.fetchall()

        return [self._row_to_event(row) for row in rows]

    async def delete_before(
        self,
        cutoff: datetime,
    ) -> int:
        """Delete events before the cutoff timestamp.

        Args:
            cutoff: Delete all events with timestamp before this

        Returns:
            Number of events deleted
        """
        if not self._initialized:
            await self.initialize()

        if not self._writer_conn:
            raise RuntimeError("Writer connection not initialized")

        cutoff_timestamp = cutoff.timestamp()

        try:
            # Count events to be deleted
            async with self._writer_conn.execute(
                """
                SELECT COUNT(*) as count FROM events
                WHERE timestamp < ? AND project_id = ?
                """,
                (cutoff_timestamp, self._project_id),
            ) as cursor:
                row = await cursor.fetchone()
                count_to_delete = row["count"] if row else 0

            if count_to_delete == 0:
                return 0

            # Delete old events
            await self._writer_conn.execute(
                """
                DELETE FROM events
                WHERE timestamp < ? AND project_id = ?
                """,
                (cutoff_timestamp, self._project_id),
            )
            await self._writer_conn.commit()

            # Checkpoint WAL
            await self._writer_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await self._writer_conn.commit()

            logger.info(
                "Deleted %s events before %s for project %s",
                count_to_delete,
                cutoff,
                self._project_id,
            )

            return count_to_delete

        except Exception as e:
            logger.error("Failed to delete events: %s", e)
            raise

    async def close(self) -> None:
        """Close storage connections and release resources."""
        if not self._initialized:
            return

        if self._writer_conn:
            try:
                await self._writer_conn.commit()
                await self._writer_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                await self._writer_conn.close()
            except Exception as e:
                logger.warning("Error closing writer connection: %s", e)
            finally:
                self._writer_conn = None

        self._initialized = False
        await asyncio.sleep(0)  # Allow cleanup
        logger.debug("SQLiteEventStorage closed: %s", self._db_path)

    # =========================================================================
    # Extended Query Operations (EventStorageQueryCapability)
    # =========================================================================

    async def get_operation_events(
        self,
        operation_id: str,
        project_id: Optional[str] = None,
    ) -> List[Event]:
        """Get all events for an operation.

        Args:
            operation_id: Operation ID to query
            project_id: Optional project filter (defaults to self.project_id)

        Returns:
            List of events ordered by timestamp
        """
        if not self._initialized:
            await self.initialize()

        project_id = project_id or self._project_id

        async with aiosqlite.connect(self._db_path, timeout=2.0) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA query_only=1")

            async with db.execute(
                """
                SELECT * FROM events
                WHERE operation_id = ? AND project_id = ?
                ORDER BY timestamp ASC
                """,
                (operation_id, project_id),
            ) as cursor:
                rows = await cursor.fetchall()

        return [self._row_to_event(row) for row in rows]

    async def get_operation_status(
        self,
        operation_id: str,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get aggregated status for an operation.

        Args:
            operation_id: Operation ID to query
            project_id: Optional project filter

        Returns:
            Dictionary with status summary
        """
        if not self._initialized:
            await self.initialize()

        project_id = project_id or self._project_id

        async with aiosqlite.connect(self._db_path, timeout=2.0) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA query_only=1")

            # Get aggregated statistics
            async with db.execute(
                """
                SELECT
                    MIN(timestamp) as start_time,
                    MAX(timestamp) as end_time,
                    COUNT(*) as event_count,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as error_count
                FROM events
                WHERE operation_id = ? AND project_id = ?
                """,
                (operation_id, project_id),
            ) as cursor:
                row = await cursor.fetchone()

                if not row or row["event_count"] == 0:
                    return {
                        "operation_id": operation_id,
                        "project_id": project_id,
                        "start_time": None,
                        "end_time": None,
                        "event_count": 0,
                        "error_count": 0,
                        "status": None,
                        "duration": None,
                    }

                start_time = row["start_time"]
                end_time = row["end_time"]
                event_count = row["event_count"]
                error_count = row["error_count"]

            # Get most recent status
            async with db.execute(
                """
                SELECT status FROM events
                WHERE operation_id = ? AND project_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (operation_id, project_id),
            ) as cursor:
                status_row = await cursor.fetchone()
                status = status_row["status"] if status_row else None

        return {
            "operation_id": operation_id,
            "project_id": project_id,
            "start_time": start_time,
            "end_time": end_time,
            "event_count": event_count,
            "error_count": error_count,
            "status": status,
            "duration": (
                (end_time - start_time) if (start_time and end_time) else None
            ),
        }

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
        if not self._initialized:
            await self.initialize()

        project_id = project_id or self._project_id

        conditions = ["project_id = ?"]
        params: List[Any] = [project_id]

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)

        if since is not None:
            conditions.append("timestamp >= ?")
            params.append(since.timestamp())

        if until is not None:
            conditions.append("timestamp <= ?")
            params.append(until.timestamp())

        where_clause = " AND ".join(conditions)
        query = f"SELECT COUNT(*) as count FROM events WHERE {where_clause}"

        async with aiosqlite.connect(self._db_path, timeout=2.0) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA query_only=1")

            async with db.execute(query, tuple(params)) as cursor:
                row = await cursor.fetchone()
                return row["count"] if row else 0

    # =========================================================================
    # Maintenance Operations (EventStorageMaintenanceCapability)
    # =========================================================================

    async def vacuum(self) -> None:
        """Compact the database to reclaim unused space."""
        if not self._initialized:
            await self.initialize()

        if not self._writer_conn:
            raise RuntimeError("Writer connection not initialized")

        try:
            logger.info("Starting database vacuum for %s", self._db_path)

            await self._writer_conn.commit()
            await self._writer_conn.execute("VACUUM")

            logger.info("Database vacuum completed for %s", self._db_path)

        except Exception as e:
            logger.error("Failed to vacuum database: %s", e)
            raise

    # =========================================================================
    # Row Conversion Helpers
    # =========================================================================

    def _event_to_row(self, event: Event) -> tuple:
        """Convert Event to SQLite row tuple.

        Args:
            event: Event object to convert

        Returns:
            Tuple suitable for SQLite insertion
        """
        return (
            event.event_id,
            event.project_id,
            event.operation_id,
            event.session_id,
            event.timestamp,
            event.event_type,
            (
                event.status.value
                if isinstance(event.status, EventStatus)
                else event.status
            ),
            event.source,
            json.dumps(event.metadata) if event.metadata else "{}",
            event.schema_version,
        )

    def _row_to_event(self, row: aiosqlite.Row) -> Event:
        """Convert SQLite row to Event.

        Args:
            row: Database row from query

        Returns:
            Event instance
        """
        return Event(
            event_id=row["event_id"],
            project_id=row["project_id"],
            operation_id=row["operation_id"],
            session_id=row["session_id"],
            timestamp=row["timestamp"],
            event_type=row["event_type"],
            status=EventStatus(row["status"]),
            source=row["source"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            schema_version=row["schema_version"],
        )
