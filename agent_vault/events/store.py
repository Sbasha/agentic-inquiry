"""SQLite-based event storage following FileTracker patterns.

This module provides the EventStore class for persisting and querying events
using SQLite with WAL mode for concurrent access.

Migration to EventStorageBackend:
    For new code, consider using SQLiteEventStorage which implements the
    EventStorageBackend protocol (DES-S2-003). This enables future backend
    swappability without modifying event system implementations.

    Example:
        from agent_vault.events.storage import SQLiteEventStorage

        storage = SQLiteEventStorage(db_path="events.db", project_id="my_project")
        await storage.initialize()
        await storage.write_events(events)
"""

import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import aiosqlite

from agent_vault.events.models import Event, EventStatus
from agent_vault.utils.retry import RetryPolicy

if TYPE_CHECKING:
    from agent_vault.config import Config

logger = logging.getLogger(__name__)


class EventStore:
    """SQLite-backed event storage with async support.
    
    Follows FileTracker patterns:
    - Lazy database initialization
    - WAL mode for concurrent reads
    - Project isolation via project_id
    - Connection-per-query for reads
    - Persistent connection for writes
    
    Attributes:
        db_path: Path to the SQLite database file
        project_id: Project identifier for data isolation
    """
    
    def __init__(
        self,
        config: Optional["Config"] = None,
        project_id: Optional[str] = None,
        db_path: Optional[Union[str, Path]] = None,
    ):
        """Initialize event store.

        Note: This constructor does NOT initialize the database. Use the async
        `initialize()` method or the factory method `from_config()` after construction.
        
        Args:
            config: Optional Config instance. If None, loads default configuration.
            project_id: Project ID for data isolation. If None, uses
                config.storage.default_project_id.
            db_path: Optional database path override. If None, uses
                config.storage.get_event_store_path().
        """
        # Import here to avoid circular dependency
        from agent_vault.config import Config
        
        # Load config if not provided
        if config is None:
            config = Config.load()
        
        self.config = config
        
        # Resolve project_id
        if project_id is None:
            project_id = config.storage.default_project_id
            if not project_id:
                raise ValueError(
                    "project_id must be provided or set as storage.default_project_id in configuration"
                )
        
        self.project_id = project_id
        
        # Determine database path
        if db_path is None:
            db_path = self.config.storage.get_event_store_path()
        
        self.db_path = str(Path(db_path).expanduser().resolve())
        
        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Connection management
        self._writer_conn: Optional[aiosqlite.Connection] = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize the event store (public API).

        This method initializes the database and sets up connections. It is safe
        to call multiple times - subsequent calls will be no-ops.

        This is the recommended explicit initialization method. Alternatively,
        initialization happens lazily on the first database operation.
        """
        await self._ensure_initialized()

    async def _ensure_initialized(self) -> None:
        """Ensure database is initialized (lazy initialization)."""
        if self._initialized:
            return
        
        async with self._init_lock:
            if self._initialized:
                return
            
            await self._init_database()
            
            # Create persistent writer connection
            self._writer_conn = await aiosqlite.connect(self.db_path, timeout=5.0)
            self._writer_conn.row_factory = aiosqlite.Row
            
            # Enable WAL mode. ``busy_timeout`` stays at 10s (was sized for
            # the old ``processing_semaphore_limit=10``; still a sensible
            # floor at the new default of 20 but the headroom is tighter).
            # Keep in sync with ``events/storage/sqlite.py`` and
            # ``onboard/providers/sqlite.py``. Revisit if SQLITE_BUSY
            # surfaces in real workloads at 20+ concurrent workers.
            await self._writer_conn.execute("PRAGMA journal_mode=WAL")
            await self._writer_conn.execute("PRAGMA synchronous=NORMAL")
            await self._writer_conn.execute("PRAGMA busy_timeout=10000")
            await self._writer_conn.commit()
            
            self._initialized = True
            logger.info("EventStore initialized: %s", self.db_path)
    
    async def _init_database(self) -> None:
        """Initialize database schema."""
        async with aiosqlite.connect(self.db_path) as db:
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
            await db.execute("CREATE INDEX IF NOT EXISTS idx_operation_id ON events(operation_id, timestamp)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_event_type ON events(event_type)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON events(timestamp)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_project_timestamp ON events(project_id, timestamp)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_status ON events(status)")
            
            await db.commit()

    async def _retry_on_locked(self, operation, max_retries: int = 3):
        """Retry database operation with exponential backoff on lock errors.

        Uses RetryPolicy for consistent retry behavior across the codebase.

        Design reference: S2-005 in .sessions/deep-architecture-review/010-tasks.md

        Args:
            operation: Async callable to retry
            max_retries: Maximum number of retry attempts (default: 3)

        Returns:
            Result of the operation

        Raises:
            Exception: If all retries are exhausted or non-retryable error occurs
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
                        logger.error("Database locked after %s attempts", policy.max_attempts)
                        raise
                else:
                    # Non-lock operational error, don't retry
                    raise
            except sqlite3.IntegrityError as e:
                # Constraint violation - log warning and don't retry
                logger.warning("Integrity constraint violation: %s", e)
                raise
            except sqlite3.DatabaseError as e:
                # Database corruption or other critical error
                logger.critical("Database error: %s", e)
                # Attempt recovery by reinitializing
                try:
                    await self._ensure_initialized()
                except Exception as recovery_error:
                    logger.critical("Failed to recover from database error: %s", recovery_error)
                raise

        # Should not reach here, but handle edge case
        if last_exception is not None:
            raise last_exception
        return None

    async def store_events(self, events: List[Event]) -> None:
        """Store multiple events (batch operation).
        
        Args:
            events: List of events to store
        """
        await self._ensure_initialized()
        
        if not events or not self._writer_conn:
            return
        
        async def _do_store():
            """Inner function for retry logic."""
            await self._writer_conn.executemany(
                """
                INSERT INTO events (
                    event_id, project_id, operation_id, session_id,
                    timestamp, event_type, status, source, metadata, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        event.event_id,
                        event.project_id,
                        event.operation_id,
                        event.session_id,
                        event.timestamp,
                        event.event_type,
                        event.status.value if isinstance(event.status, EventStatus) else event.status,
                        event.source,
                        json.dumps(event.metadata) if event.metadata else "{}",
                        event.schema_version,
                    )
                    for event in events
                ],
            )
            await self._writer_conn.commit()
        
        try:
            await self._retry_on_locked(_do_store)
        except sqlite3.IntegrityError:
            # Already logged in retry handler, just continue
            logger.warning("Skipping %s events due to integrity constraint", len(events))
        except sqlite3.DatabaseError:
            # Critical error already logged, continue without raising to avoid breaking caller
            logger.error("Failed to store %s events due to database error", len(events))
        except Exception as e:
            logger.error("Failed to store %s events: %s", len(events), e)
            # Don't raise - event tracking failures should not break system operations
    
    def _row_to_event(self, row: aiosqlite.Row) -> Event:
        """Convert database row to Event.
        
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

    async def get_operation_events(
        self,
        operation_id: str,
        project_id: Optional[str] = None,
    ) -> List[Event]:
        """Get all events for an operation.
        
        Args:
            operation_id: Operation ID to query
            project_id: Optional project ID filter (defaults to self.project_id)
            
        Returns:
            List of events ordered by timestamp
        """
        await self._ensure_initialized()
        
        project_id = project_id or self.project_id
        
        async with aiosqlite.connect(self.db_path, timeout=2.0) as db:
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

    @classmethod
    async def from_config(
        cls,
        config: Optional["Config"] = None,
        project_id: Optional[str] = None,
        db_path: Optional[Union[str, Path]] = None,
    ) -> "EventStore":
        """Create and initialize event store.
        
        This is the recommended way to create an EventStore instance as it
        properly initializes the database asynchronously.
        
        Args:
            config: Optional Config instance. If None, loads default configuration.
            project_id: Project ID for data isolation. If None, uses
                config.storage.default_project_id.
            db_path: Optional database path override. If None, uses
                config.storage.get_event_store_path().
                
        Returns:
            Initialized EventStore instance
        """
        store = cls(config=config, project_id=project_id, db_path=db_path)
        await store._ensure_initialized()
        return store
    
    async def get_events_by_type(
        self,
        event_type: str,
        project_id: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Event]:
        """Get events filtered by event type.
        
        Args:
            event_type: Event type to filter by (e.g., "indexing.started")
            project_id: Optional project ID filter (defaults to self.project_id)
            limit: Maximum number of events to return (default: 1000)
            
        Returns:
            List of events ordered by timestamp descending
        """
        await self._ensure_initialized()
        
        project_id = project_id or self.project_id
        
        async with aiosqlite.connect(self.db_path, timeout=2.0) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA query_only=1")
            
            async with db.execute(
                """
                SELECT * FROM events
                WHERE event_type = ? AND project_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (event_type, project_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        
        return [self._row_to_event(row) for row in rows]

    async def get_events_by_time_range(
        self,
        start_time: float,
        end_time: float,
        project_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Event]:
        """Get events within a timestamp range.
        
        Args:
            start_time: Start timestamp (Unix timestamp with microseconds)
            end_time: End timestamp (Unix timestamp with microseconds)
            project_id: Optional project ID filter (defaults to self.project_id)
            event_type: Optional event type filter
            limit: Maximum number of events to return (default: 1000)
            
        Returns:
            List of events ordered by timestamp ascending
        """
        await self._ensure_initialized()
        
        project_id = project_id or self.project_id
        
        async with aiosqlite.connect(self.db_path, timeout=2.0) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA query_only=1")
            
            if event_type:
                query = """
                    SELECT * FROM events
                    WHERE timestamp >= ? AND timestamp <= ?
                    AND project_id = ? AND event_type = ?
                    ORDER BY timestamp ASC
                    LIMIT ?
                """
                params: tuple = (start_time, end_time, project_id, event_type, limit)
            else:
                query = """
                    SELECT * FROM events
                    WHERE timestamp >= ? AND timestamp <= ?
                    AND project_id = ?
                    ORDER BY timestamp ASC
                    LIMIT ?
                """
                params = (start_time, end_time, project_id, limit)
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
        
        return [self._row_to_event(row) for row in rows]

    async def get_latest_events(
        self,
        limit: int = 100,
        project_id: Optional[str] = None,
        status: Optional[EventStatus] = None,
    ) -> List[Event]:
        """Get the latest N events.
        
        Args:
            limit: Maximum number of events to return (default: 100)
            project_id: Optional project ID filter (defaults to self.project_id)
            status: Optional status filter (e.g., EventStatus.FAILED)
            
        Returns:
            List of events ordered by timestamp descending
        """
        await self._ensure_initialized()
        
        project_id = project_id or self.project_id
        
        async with aiosqlite.connect(self.db_path, timeout=2.0) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA query_only=1")
            
            if status:
                query = """
                    SELECT * FROM events
                    WHERE project_id = ? AND status = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """
                params: tuple = (project_id, status.value, limit)
            else:
                query = """
                    SELECT * FROM events
                    WHERE project_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """
                params = (project_id, limit)
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
        
        return [self._row_to_event(row) for row in rows]

    async def query_events(
        self,
        event_type: Optional[str] = None,
        min_timestamp: Optional[float] = None,
        max_timestamp: Optional[float] = None,
        filters: Optional[Dict[str, Any]] = None,
        order_by: str = "timestamp",
        order_direction: str = "desc",
        limit: int = 1000,
        project_id: Optional[str] = None,
    ) -> List[Event]:
        """Unified event query with flexible filtering and ordering.
        
        This method provides a flexible way to query events with multiple
        filter criteria, timestamp ranges, and custom ordering.
        
        Args:
            event_type: Optional event type filter (e.g., "indexing.started")
            min_timestamp: Only return events after this timestamp (exclusive)
            max_timestamp: Only return events before this timestamp (inclusive)
            filters: Optional dict of field filters. Supported fields:
                - operation_id: Filter by operation ID
                - session_id: Filter by session ID
                - status: Filter by status (string or EventStatus)
                - source: Filter by source component
            order_by: Field to sort by. Valid: "timestamp", "event_type", "status"
                (default: "timestamp")
            order_direction: Sort direction, "asc" or "desc" (default: "desc")
            limit: Maximum number of events to return (default: 1000)
            project_id: Optional project ID filter (defaults to self.project_id)
            
        Returns:
            List of events matching the criteria
            
        Example:
            >>> # Get the most recent FILE_INDEXED event for an operation
            >>> events = await store.query_events(
            ...     event_type="indexing.file.indexed",
            ...     filters={"operation_id": "op_123"},
            ...     order_by="timestamp",
            ...     order_direction="desc",
            ...     limit=1
            ... )
        """
        await self._ensure_initialized()
        
        project_id = project_id or self.project_id
        
        # Validate order_by to prevent SQL injection
        valid_order_fields = {"timestamp", "event_type", "status", "source"}
        if order_by not in valid_order_fields:
            raise ValueError(
                f"Invalid order_by field: {order_by}. "
                f"Valid fields: {valid_order_fields}"
            )
        
        # Validate order_direction
        order_direction = order_direction.upper()
        if order_direction not in ("ASC", "DESC"):
            raise ValueError(
                f"Invalid order_direction: {order_direction}. Must be 'asc' or 'desc'"
            )
        
        # Build query dynamically
        conditions = ["project_id = ?"]
        params: List[Any] = [project_id]
        
        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)
        
        if min_timestamp is not None:
            conditions.append("timestamp > ?")
            params.append(min_timestamp)
        
        if max_timestamp is not None:
            conditions.append("timestamp <= ?")
            params.append(max_timestamp)
        
        # Process additional filters
        if filters:
            if "operation_id" in filters:
                conditions.append("operation_id = ?")
                params.append(filters["operation_id"])
            
            if "session_id" in filters:
                conditions.append("session_id = ?")
                params.append(filters["session_id"])
            
            if "status" in filters:
                status_value = filters["status"]
                if isinstance(status_value, EventStatus):
                    status_value = status_value.value
                conditions.append("status = ?")
                params.append(status_value)
            
            if "source" in filters:
                conditions.append("source = ?")
                params.append(filters["source"])
        
        # Add limit parameter
        params.append(limit)
        
        # Construct final query
        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT * FROM events
            WHERE {where_clause}
            ORDER BY {order_by} {order_direction}
            LIMIT ?
        """
        
        async with aiosqlite.connect(self.db_path, timeout=2.0) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA query_only=1")
            
            async with db.execute(query, tuple(params)) as cursor:
                rows = await cursor.fetchall()
        
        return [self._row_to_event(row) for row in rows]

    async def get_operation_status(
        self,
        operation_id: str,
        project_id: Optional[str] = None,
    ) -> dict:
        """Get operation status summary.
        
        Args:
            operation_id: Operation ID to query
            project_id: Optional project ID filter (defaults to self.project_id)
            
        Returns:
            Dictionary with operation summary:
            - operation_id: The operation ID
            - project_id: The project ID
            - start_time: Timestamp of first event
            - end_time: Timestamp of last event
            - event_count: Total number of events
            - error_count: Number of failed events
            - status: Most recent event status
            - duration: Time between first and last event (seconds)
        """
        await self._ensure_initialized()
        
        project_id = project_id or self.project_id
        
        async with aiosqlite.connect(self.db_path, timeout=2.0) as db:
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
            "duration": (end_time - start_time) if (start_time and end_time) else None,
        }

    async def count_events(
        self,
        project_id: Optional[str] = None,
        event_type: Optional[str] = None,
        status: Optional[EventStatus] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> int:
        """Count events matching filters (for pagination support).
        
        Args:
            project_id: Optional project ID filter (defaults to self.project_id)
            event_type: Optional event type filter
            status: Optional status filter
            start_time: Optional start timestamp filter
            end_time: Optional end timestamp filter
            
        Returns:
            Count of matching events
        """
        await self._ensure_initialized()
        
        project_id = project_id or self.project_id
        
        # Build query dynamically based on filters
        conditions = ["project_id = ?"]
        params: list = [project_id]
        
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        
        if status:
            conditions.append("status = ?")
            params.append(status.value)
        
        if start_time is not None:
            conditions.append("timestamp >= ?")
            params.append(start_time)
        
        if end_time is not None:
            conditions.append("timestamp <= ?")
            params.append(end_time)
        
        where_clause = " AND ".join(conditions)
        query = f"SELECT COUNT(*) as count FROM events WHERE {where_clause}"
        
        async with aiosqlite.connect(self.db_path, timeout=2.0) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA query_only=1")
            
            async with db.execute(query, tuple(params)) as cursor:
                row = await cursor.fetchone()
                return row["count"] if row else 0

    async def cleanup_old_events(
        self,
        retention_days: int,
        project_id: Optional[str] = None,
    ) -> int:
        """Delete events older than retention period.
        
        This method removes events older than the specified number of days
        and performs a WAL checkpoint to release disk space.
        
        Args:
            retention_days: Number of days to retain events (events older than this are deleted)
            project_id: Optional project ID filter (defaults to self.project_id).
                If None, cleans up events for the current project only.
            
        Returns:
            Count of deleted events
            
        Example:
            # Delete events older than 30 days
            deleted_count = await store.cleanup_old_events(retention_days=30)
            print(f"Deleted {deleted_count} old events")
        """
        await self._ensure_initialized()
        
        if retention_days <= 0:
            raise ValueError("retention_days must be positive")
        
        project_id = project_id or self.project_id
        
        # Calculate cutoff timestamp (current time - retention_days)
        import time
        cutoff_timestamp = time.time() - (retention_days * 24 * 60 * 60)
        
        if not self._writer_conn:
            raise RuntimeError("Writer connection not initialized")
        
        try:
            # Count events to be deleted (for logging)
            async with self._writer_conn.execute(
                """
                SELECT COUNT(*) as count FROM events
                WHERE timestamp < ? AND project_id = ?
                """,
                (cutoff_timestamp, project_id),
            ) as cursor:
                row = await cursor.fetchone()
                count_to_delete = row["count"] if row else 0
            
            if count_to_delete == 0:
                logger.info("No events older than %s days to delete", retention_days)
                return 0
            
            # Delete old events
            await self._writer_conn.execute(
                """
                DELETE FROM events
                WHERE timestamp < ? AND project_id = ?
                """,
                (cutoff_timestamp, project_id),
            )
            await self._writer_conn.commit()
            
            # Checkpoint WAL to release disk space
            await self._writer_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await self._writer_conn.commit()
            
            logger.info("Deleted %s events older than %s days "
                "for project %s", count_to_delete, retention_days, project_id)
            
            return count_to_delete
            
        except Exception as e:
            logger.error("Failed to cleanup old events: %s", e)
            raise

    async def vacuum(self) -> None:
        """Compact the database to reclaim unused space.
        
        This is a manual maintenance operation that should be run periodically
        to optimize database size and performance. It rebuilds the database file
        to eliminate fragmentation and reclaim space from deleted records.
        
        Note:
            - This operation requires exclusive access to the database
            - It may take significant time for large databases
            - The database file will be locked during the operation
            - This should typically be run during maintenance windows
            
        Warning:
            VACUUM requires temporary disk space equal to the size of the database.
            Ensure sufficient disk space is available before running.
            
        Example:
            # Run during maintenance window
            await store.vacuum()
            print("Database compaction complete")
        """
        await self._ensure_initialized()
        
        if not self._writer_conn:
            raise RuntimeError("Writer connection not initialized")
        
        try:
            logger.info("Starting database vacuum for %s", self.db_path)
            
            # VACUUM cannot be run inside a transaction
            # Ensure any pending transaction is committed
            await self._writer_conn.commit()
            
            # Run VACUUM
            await self._writer_conn.execute("VACUUM")
            
            logger.info("Database vacuum completed for %s", self.db_path)
            
        except Exception as e:
            logger.error("Failed to vacuum database: %s", e)
            raise

    async def close(self) -> None:
        """Close database connections.
        
        Closes the persistent writer connection and cleans up resources.
        Performs a WAL checkpoint before close to ensure all data is written
        and lock files are released.
        """
        if not self._initialized:
            return
        
        if self._writer_conn:
            try:
                # Commit any pending transactions
                await self._writer_conn.commit()
                # Checkpoint WAL to release locks and consolidate data
                await self._writer_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                # Close the connection
                await self._writer_conn.close()
            except Exception as e:
                logger.warning("Error closing writer connection: %s", e)
            finally:
                self._writer_conn = None
        
        self._initialized = False
        
        # Give asyncio a chance to clean up any pending tasks
        await asyncio.sleep(0)
        
        logger.debug("EventStore closed: %s", self.db_path)
