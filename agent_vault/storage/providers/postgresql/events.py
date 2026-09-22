"""PostgreSQL event storage provider.

This module implements EventStorageProtocol using PostgreSQL for persistent
event storage with efficient querying and maintenance capabilities.

Features:
    - Atomic batch writes with transaction support
    - Flexible event querying with filters
    - Operation status aggregation
    - Retention policy enforcement via delete_before
    - PostgreSQL-specific maintenance (VACUUM ANALYZE)

Table schema:
    - {prefix}e_events: Event records with JSONB metadata
    - {prefix}e_operations: Operation tracking (optional future use)

Example:
    >>> manager = PostgresConnectionManager(connection_string="postgresql://...")
    >>> await manager.initialize()
    >>> provider = PostgresEventProvider(manager, project_id="myproject")
    >>> await provider.initialize()
    >>> count = await provider.write_events([event1, event2])
    >>> events = await provider.query_events(event_type="indexing.complete")
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agent_vault.events.models import Event, EventStatus
from agent_vault.storage.protocols.events import EventStorageProtocol
from agent_vault.storage.providers.postgresql.schemas import (
    EVENTS_TABLE,
    SchemaGenerator,
)

if TYPE_CHECKING:
    from agent_vault.storage.providers.postgresql.connection import (
        PostgresConnectionManager,
    )

logger = logging.getLogger(__name__)


class PostgresEventProvider(EventStorageProtocol):
    """PostgreSQL implementation of event storage.

    Uses asyncpg for native async PostgreSQL operations. Events are stored
    in a table with JSONB metadata for flexible querying.

    Attributes:
        connection_manager: Shared PostgreSQL connection manager
        project_id: Project identifier for data isolation
        embedding_dim: Embedding dimension (not used for events, included for API)
        _initialized: Whether initialize() has been called
        _events_table: Full name of the events table

    Thread Safety:
        All operations are async-safe. The underlying connection pool
        handles concurrent access.

    Example:
        >>> provider = PostgresEventProvider(manager, "myproject")
        >>> await provider.initialize()
        >>> await provider.write_events([event])
    """

    SUPPORTED_ROLES = frozenset({"events"})

    def __init__(
        self,
        connection_manager: "PostgresConnectionManager",
        project_id: str,
        *,
        embedding_dim: int = 384,
    ) -> None:
        """Initialize PostgreSQL event provider.

        Args:
            connection_manager: PostgresConnectionManager instance
            project_id: Project identifier for data isolation
            embedding_dim: Embedding dimension (not used for events)
        """
        self._connection_manager = connection_manager
        self._project_id = project_id
        self._embedding_dim = embedding_dim
        self._initialized = False

        # Generate table names
        self._schema_generator = SchemaGenerator(
            prefix=connection_manager.table_prefix,
            embedding_dim=embedding_dim,
        )
        self._events_table = self._schema_generator.get_table_name(EVENTS_TABLE)

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        project_id: str,
    ) -> "PostgresEventProvider":
        """Create provider from configuration dict.

        Supports both direct connection_string and host-based params
        (e.g. RDS direct connections with host, user, password fields).

        Args:
            config: Configuration with connection_string or host-based params
            project_id: Project ID for data isolation

        Returns:
            Configured PostgresEventProvider instance
        """
        from agent_vault.storage.providers.postgresql.connection import (
            PostgresConnectionManager,
        )
        from agent_vault.storage.providers.postgresql.vector import (
            PostgresVectorProvider,
        )

        resolved_config = dict(config)
        if not resolved_config.get("connection_string"):
            resolved_config["connection_string"] = PostgresVectorProvider._build_dsn_from_config(config)

        manager = PostgresConnectionManager.from_config(
            resolved_config,
            table_prefix=config.get("table_prefix", "agv_"),
        )

        return cls(
            connection_manager=manager,
            project_id=project_id,
            embedding_dim=config.get("embedding_dim", 384),
        )

    @property
    def project_id(self) -> str:
        """Get project identifier."""
        return self._project_id

    # =========================================================================
    # Lifecycle Operations
    # =========================================================================

    async def initialize(self) -> None:
        """Initialize storage and create schema if needed.

        Creates the events table and indexes if they don't exist.
        Idempotent - safe to call multiple times.

        Raises:
            RuntimeError: If initialization fails
        """
        if self._initialized:
            return

        try:
            # Ensure connection manager is initialized
            if not self._connection_manager.is_initialized:
                await self._connection_manager.initialize()

            # Create events tables
            statements = self._schema_generator.get_create_statements("events")
            async with self._connection_manager.transaction() as conn:
                for stmt in statements:
                    await conn.execute(stmt)

            self._initialized = True
            logger.info(
                "PostgresEventProvider initialized for project %s",
                self._project_id,
            )

        except Exception as e:
            raise RuntimeError(f"Failed to initialize event storage: {e}") from e

    async def close(self) -> None:
        """Close storage connections and release resources.

        Note: Does not close the shared connection manager.
        """
        self._initialized = False
        logger.debug("PostgresEventProvider closed for project %s", self._project_id)

    # =========================================================================
    # Write Operations
    # =========================================================================

    async def write_events(
        self,
        events: List[Event],
    ) -> int:
        """Write a batch of events to storage.

        Events are written atomically in a transaction.

        Args:
            events: List of Event objects to persist

        Returns:
            Number of events successfully written

        Raises:
            RuntimeError: If storage not initialized
        """
        if not self._initialized:
            raise RuntimeError("Provider not initialized. Call initialize() first.")

        if not events:
            return 0

        query = f"""
            INSERT INTO {self._events_table} (
                id, project_id, operation_id, event_type, severity,
                message, details, file_path, entity_id, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (id) DO UPDATE SET
                event_type = EXCLUDED.event_type,
                severity = EXCLUDED.severity,
                message = EXCLUDED.message,
                details = EXCLUDED.details,
                created_at = EXCLUDED.created_at
        """

        rows = []
        for event in events:
            # Map Event fields to table columns
            # severity maps from status, message from metadata.get("message")
            severity = self._status_to_severity(event.status)
            message = event.metadata.get("message", "")

            # Store full event data in details
            details = {
                "source": event.source,
                "session_id": event.session_id,
                "schema_version": event.schema_version,
                **event.metadata,
            }

            # Extract file_path and entity_id if present
            file_path = event.metadata.get("file_path") or event.metadata.get("path")
            entity_id = event.metadata.get("entity_id")

            rows.append((
                event.event_id,
                event.project_id or self._project_id,
                event.operation_id or "",
                event.event_type,
                severity,
                message,
                json.dumps(details),
                file_path,
                entity_id,
                datetime.fromtimestamp(event.timestamp),
            ))

        try:
            async with self._connection_manager.transaction() as conn:
                await conn.executemany(query, rows)

            logger.debug("Wrote %d events for project %s", len(events), self._project_id)
            return len(events)

        except Exception as e:
            logger.error("Failed to write events: %s", e)
            raise RuntimeError(f"Failed to write events: {e}") from e

    def _status_to_severity(self, status: EventStatus) -> str:
        """Map EventStatus to severity level."""
        mapping = {
            EventStatus.STARTED: "info",
            EventStatus.PROGRESS: "info",
            EventStatus.COMPLETED: "info",
            EventStatus.FAILED: "error",
        }
        return mapping.get(status, "info")

    def _severity_to_status(self, severity: str) -> EventStatus:
        """Map severity level to EventStatus."""
        if severity == "error":
            return EventStatus.FAILED
        return EventStatus.PROGRESS

    # =========================================================================
    # Query Operations
    # =========================================================================

    async def query_events(
        self,
        event_type: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Event]:
        """Query events with optional filters.

        Returns events matching criteria, ordered by timestamp descending.

        Args:
            event_type: Filter by event type (e.g., "indexing.started")
            since: Return events after this timestamp (exclusive)
            until: Return events before this timestamp (inclusive)
            limit: Maximum number of events to return

        Returns:
            List of matching events, ordered by timestamp descending

        Raises:
            RuntimeError: If storage not initialized
        """
        if not self._initialized:
            raise RuntimeError("Provider not initialized. Call initialize() first.")

        conditions = ["project_id = $1"]
        params: List[Any] = [self._project_id]
        param_idx = 2

        if event_type is not None:
            conditions.append(f"event_type = ${param_idx}")
            params.append(event_type)
            param_idx += 1

        if since is not None:
            conditions.append(f"created_at > ${param_idx}")
            params.append(since)
            param_idx += 1

        if until is not None:
            conditions.append(f"created_at <= ${param_idx}")
            params.append(until)
            param_idx += 1

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT id, project_id, operation_id, event_type, severity,
                   message, details, file_path, entity_id, created_at
            FROM {self._events_table}
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_idx}
        """
        params.append(limit)

        try:
            rows = await self._connection_manager.fetch(query, *params)
            return [self._row_to_event(row) for row in rows]

        except Exception as e:
            logger.error("Failed to query events: %s", e)
            raise RuntimeError(f"Failed to query events: {e}") from e

    async def get_operation_events(
        self,
        operation_id: str,
        project_id: Optional[str] = None,
    ) -> List[Event]:
        """Get all events for a specific operation.

        Returns events in chronological order (ascending).

        Args:
            operation_id: Operation ID to query
            project_id: Optional project filter (defaults to current project)

        Returns:
            List of events ordered by timestamp ascending

        Raises:
            RuntimeError: If storage not initialized
        """
        if not self._initialized:
            raise RuntimeError("Provider not initialized. Call initialize() first.")

        effective_project_id = project_id or self._project_id

        query = f"""
            SELECT id, project_id, operation_id, event_type, severity,
                   message, details, file_path, entity_id, created_at
            FROM {self._events_table}
            WHERE project_id = $1 AND operation_id = $2
            ORDER BY created_at ASC
        """

        try:
            rows = await self._connection_manager.fetch(
                query, effective_project_id, operation_id
            )
            return [self._row_to_event(row) for row in rows]

        except Exception as e:
            logger.error("Failed to get operation events: %s", e)
            raise RuntimeError(f"Failed to get operation events: {e}") from e

    async def get_operation_status(
        self,
        operation_id: str,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get aggregated status for an operation.

        Returns summary statistics for all events in the operation.

        Args:
            operation_id: Operation ID to query
            project_id: Optional project filter (defaults to current project)

        Returns:
            Dictionary with status summary

        Raises:
            RuntimeError: If storage not initialized
        """
        if not self._initialized:
            raise RuntimeError("Provider not initialized. Call initialize() first.")

        effective_project_id = project_id or self._project_id

        query = f"""
            SELECT
                COUNT(*) as event_count,
                COUNT(*) FILTER (WHERE severity = 'error') as error_count,
                MIN(created_at) as start_time,
                MAX(created_at) as end_time,
                (SELECT event_type FROM {self._events_table}
                 WHERE project_id = $1 AND operation_id = $2
                 ORDER BY created_at DESC LIMIT 1) as latest_type,
                (SELECT severity FROM {self._events_table}
                 WHERE project_id = $1 AND operation_id = $2
                 ORDER BY created_at DESC LIMIT 1) as latest_severity
            FROM {self._events_table}
            WHERE project_id = $1 AND operation_id = $2
        """

        try:
            row = await self._connection_manager.fetchrow(
                query, effective_project_id, operation_id
            )

            if row is None or row["event_count"] == 0:
                return {
                    "operation_id": operation_id,
                    "project_id": effective_project_id,
                    "start_time": None,
                    "end_time": None,
                    "event_count": 0,
                    "error_count": 0,
                    "status": None,
                    "duration": None,
                }

            start_time = row["start_time"]
            end_time = row["end_time"]
            duration = None
            if start_time and end_time:
                duration = (end_time - start_time).total_seconds()

            # Map severity to status
            latest_severity = row["latest_severity"]
            status = self._severity_to_status(latest_severity) if latest_severity else None

            return {
                "operation_id": operation_id,
                "project_id": effective_project_id,
                "start_time": start_time,
                "end_time": end_time,
                "event_count": row["event_count"],
                "error_count": row["error_count"],
                "status": status.value if status else None,
                "duration": duration,
            }

        except Exception as e:
            logger.error("Failed to get operation status: %s", e)
            raise RuntimeError(f"Failed to get operation status: {e}") from e

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
        if not self._initialized:
            raise RuntimeError("Provider not initialized. Call initialize() first.")

        effective_project_id = project_id or self._project_id

        conditions = ["project_id = $1"]
        params: List[Any] = [effective_project_id]
        param_idx = 2

        if event_type is not None:
            conditions.append(f"event_type = ${param_idx}")
            params.append(event_type)
            param_idx += 1

        if since is not None:
            conditions.append(f"created_at > ${param_idx}")
            params.append(since)
            param_idx += 1

        if until is not None:
            conditions.append(f"created_at <= ${param_idx}")
            params.append(until)
            param_idx += 1

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT COUNT(*) FROM {self._events_table}
            WHERE {where_clause}
        """

        try:
            result = await self._connection_manager.fetchval(query, *params)
            return result or 0

        except Exception as e:
            logger.error("Failed to count events: %s", e)
            raise RuntimeError(f"Failed to count events: {e}") from e

    # =========================================================================
    # Maintenance Operations
    # =========================================================================

    async def delete_before(
        self,
        cutoff: datetime,
    ) -> int:
        """Delete events before the cutoff timestamp.

        Used for retention policy enforcement.

        Args:
            cutoff: Delete all events with timestamp before this

        Returns:
            Number of events deleted

        Raises:
            RuntimeError: If storage not initialized or operation fails
        """
        if not self._initialized:
            raise RuntimeError("Provider not initialized. Call initialize() first.")

        query = f"""
            DELETE FROM {self._events_table}
            WHERE project_id = $1 AND created_at < $2
        """

        try:
            result = await self._connection_manager.execute(
                query, self._project_id, cutoff
            )
            # Parse "DELETE N" result
            deleted = int(result.split()[-1]) if result else 0
            logger.info(
                "Deleted %d events before %s for project %s",
                deleted, cutoff, self._project_id
            )
            return deleted

        except Exception as e:
            logger.error("Failed to delete events: %s", e)
            raise RuntimeError(f"Failed to delete events: {e}") from e

    async def run_maintenance(self) -> Dict[str, Any]:
        """Run storage maintenance operations.

        Performs PostgreSQL-specific optimization:
        - VACUUM ANALYZE on events table

        Returns:
            Dict with maintenance results

        Raises:
            RuntimeError: If storage not initialized or maintenance fails
        """
        if not self._initialized:
            raise RuntimeError("Provider not initialized. Call initialize() first.")

        try:
            # Count before maintenance
            count = await self.count_events()

            # VACUUM ANALYZE the events table
            # Note: VACUUM cannot run inside a transaction
            async with self._connection_manager.acquire() as conn:
                await conn.execute(f"VACUUM ANALYZE {self._events_table}")

            logger.info(
                "Maintenance completed for project %s: %d events",
                self._project_id, count
            )

            return {
                "project_id": self._project_id,
                "events_count": count,
                "tables_vacuumed": [self._events_table],
                "status": "completed",
            }

        except Exception as e:
            logger.error("Failed to run maintenance: %s", e)
            raise RuntimeError(f"Failed to run maintenance: {e}") from e

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _row_to_event(self, row) -> Event:
        """Convert database row to Event object."""
        # Parse details JSON
        details = row["details"]
        if isinstance(details, str):
            details = json.loads(details)

        # Extract fields from details
        source = details.pop("source", "")
        session_id = details.pop("session_id", None)
        schema_version = details.pop("schema_version", "1.0")

        # Merge remaining details into metadata
        metadata = dict(details)
        if row["message"]:
            metadata["message"] = row["message"]
        if row["file_path"]:
            metadata["file_path"] = row["file_path"]
        if row["entity_id"]:
            metadata["entity_id"] = row["entity_id"]

        return Event(
            event_id=row["id"],
            project_id=row["project_id"],
            operation_id=row["operation_id"] if row["operation_id"] else None,
            session_id=session_id,
            timestamp=row["created_at"].timestamp(),
            event_type=row["event_type"],
            status=self._severity_to_status(row["severity"]),
            source=source,
            metadata=metadata,
            schema_version=schema_version,
        )

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"PostgresEventProvider("
            f"project_id={self._project_id!r}, "
            f"initialized={self._initialized})"
        )
