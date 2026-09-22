"""Schema version tracking and dimension mismatch detection for PostgreSQL.

This module provides schema evolution support by tracking schema versions,
detecting embedding dimension mismatches, and coordinating migrations using
advisory locks.

Design decisions:
    - Integer versioning: Simple auto-increment for easy ordering
    - Advisory locks: Prevent concurrent migrations
    - Dimension detection: Query pg_attribute for actual column type
    - Fail-fast: Raise error on mismatch rather than silent corruption

Example:
    >>> tracker = SchemaVersionTracker(connection_manager)
    >>> await tracker.ensure_meta_table()
    >>> mismatch = await tracker.detect_dimension_mismatch("chunks", 1536)
    >>> if mismatch:
    ...     print(f"Dimension mismatch: {mismatch.configured} vs {mismatch.actual}")
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from agent_vault.storage.errors import (
    DimensionMismatch as _SharedDimensionMismatch,
    SchemaMismatchError as SchemaMismatchError,  # re-export for backcompat
)

if TYPE_CHECKING:
    import asyncpg

    from .connection import PostgresConnectionManager

logger = logging.getLogger(__name__)

# Schema metadata table name
SCHEMA_META_TABLE = "_agv_schema_meta"


class MigrationError(Exception):
    """Raised when schema migration fails."""

    pass


@dataclass
class SchemaInfo:
    """Schema metadata for a table.

    Attributes:
        table_name: Name of the table
        schema_version: Current schema version (integer)
        embedding_dimension: Vector embedding dimension
        index_type: Type of index (hnsw, ivfflat, none)
        created_at: Timestamp when schema was created
        updated_at: Timestamp of last schema update
    """

    table_name: str
    schema_version: int
    embedding_dimension: int
    index_type: str
    created_at: datetime
    updated_at: datetime


# Backward-compat re-export: ``DimensionMismatch`` has been moved to
# ``agent_vault.storage.errors`` so LanceDB and future backends can share it.
# The shared class has an extra ``backend`` field; this module constructs it
# with ``backend="postgresql"``.
DimensionMismatch = _SharedDimensionMismatch


class SchemaVersionTracker:
    """Tracks schema versions and detects dimension mismatches.

    This class implements schema evolution support from FR-3, including:
    - Schema metadata table management
    - Dimension mismatch detection via pg_attribute
    - Advisory locks for migration coordination
    - Version increment after successful migrations

    Example:
        >>> tracker = SchemaVersionTracker(connection_manager)
        >>> await tracker.ensure_meta_table()
        >>> info = await tracker.get_schema_info("agv_v_chunks")
        >>> print(f"Version: {info.schema_version}")
    """

    # Advisory lock ID for migration coordination (AC-6)
    # Using "agvS" in hex: 0x43495153
    ADVISORY_LOCK_ID = 0x43495153

    def __init__(self, connection_manager: "PostgresConnectionManager"):
        """Initialize schema version tracker.

        Args:
            connection_manager: PostgreSQL connection manager
        """
        self._conn_manager = connection_manager

    async def ensure_meta_table(self) -> None:
        """Create schema metadata table if not exists.

        This table tracks schema version, embedding dimension, and index type
        for each storage table. Used for migration coordination and
        dimension mismatch detection.

        Example:
            >>> await tracker.ensure_meta_table()
        """
        async with self._conn_manager.acquire() as conn:
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {SCHEMA_META_TABLE} (
                    table_name TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    embedding_dimension INTEGER NOT NULL,
                    index_type TEXT NOT NULL DEFAULT 'ivfflat',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """
            )
        logger.debug("Schema metadata table ensured: %s", SCHEMA_META_TABLE)

    async def get_schema_info(self, table_name: str) -> Optional[SchemaInfo]:
        """Get current schema information for a table.

        Args:
            table_name: Name of the table to query

        Returns:
            SchemaInfo object if table has metadata, None otherwise

        Example:
            >>> info = await tracker.get_schema_info("agv_v_chunks")
            >>> if info:
            ...     print(f"Version: {info.schema_version}")
        """
        async with self._conn_manager.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {SCHEMA_META_TABLE} WHERE table_name = $1", table_name
            )
            if row is None:
                return None

            return SchemaInfo(
                table_name=row["table_name"],
                schema_version=row["schema_version"],
                embedding_dimension=row["embedding_dimension"],
                index_type=row["index_type"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    async def detect_dimension_mismatch(
        self, table_name: str, configured_dimension: int
    ) -> Optional[DimensionMismatch]:
        """Check if configured dimension matches existing table.

        Queries pg_attribute to get the actual vector column dimension
        and compares with configured dimension. This is critical for
        preventing silent data corruption when dimension changes.

        Args:
            table_name: Name of the table to check
            configured_dimension: Dimension from BackendConfig

        Returns:
            DimensionMismatch if mismatch detected, None if dimensions match
            or table doesn't exist

        Example:
            >>> mismatch = await tracker.detect_dimension_mismatch(
            ...     "agv_v_chunks", 1536
            ... )
            >>> if mismatch:
            ...     raise SchemaMismatchError(str(mismatch))
        """
        async with self._conn_manager.acquire() as conn:
            # Query actual column type from pg_attribute
            # pgvector stores dimension directly in atttypmod (no header offset)
            actual_dim = await conn.fetchval(
                """
                SELECT atttypmod
                FROM pg_attribute a
                JOIN pg_class c ON a.attrelid = c.oid
                WHERE c.relname = $1 AND a.attname = 'embedding'
            """,
                table_name,
            )

            if actual_dim is None:
                # Table or column doesn't exist - not a mismatch
                return None

            if actual_dim != configured_dimension:
                logger.error(
                    "Dimension mismatch detected: table=%s, configured=%d, actual=%d",
                    table_name,
                    configured_dimension,
                    actual_dim,
                )
                return DimensionMismatch(
                    backend="postgresql",
                    table_name=table_name,
                    configured=configured_dimension,
                    actual=actual_dim,
                    # Explicit, matching the hard-coded ``attname = 'embedding'``
                    # literal in the pg_attribute query above — if that column
                    # ever moves, grep for "embedding" catches both sides.
                    column="embedding",
                    remediation=(
                        "To migrate, run: "
                        "agv schema migrate --project <name> --confirm-data-loss\n"
                        "This drops and recreates the embedding column, "
                        "requiring a full re-index."
                    ),
                )

            return None

    async def acquire_migration_lock(
        self, conn: "asyncpg.Connection", timeout_seconds: int = 30
    ) -> bool:
        """Acquire advisory lock for migration coordination.

        Uses pg_try_advisory_lock with retry loop to implement timeout.
        Prevents concurrent migrations from corrupting data.

        Args:
            conn: Database connection (must remain open during migration)
            timeout_seconds: Maximum time to wait for lock. Default is 30 seconds.
                This can be configured via config.storage.backend_timeouts.migration_lock_timeout.

        Returns:
            True if lock acquired, False if timeout exceeded

        Example:
            >>> async with conn_manager.acquire() as conn:
            ...     acquired = await tracker.acquire_migration_lock(conn)
            ...     if not acquired:
            ...         raise MigrationError("Another migration in progress")
            ...     try:
            ...         # Perform migration
            ...         pass
            ...     finally:
            ...         await tracker.release_migration_lock(conn)
        """
        start_time = time.monotonic()
        retry_interval = 0.5  # seconds

        while (time.monotonic() - start_time) < timeout_seconds:
            result = await conn.fetchval(
                "SELECT pg_try_advisory_lock($1)", self.ADVISORY_LOCK_ID
            )
            if result:
                logger.debug("Migration advisory lock acquired")
                return True

            # Wait before retry
            await asyncio.sleep(retry_interval)

        # Timeout exceeded
        logger.warning(
            "Failed to acquire migration lock after %ds. "
            "Another migration may be in progress.",
            timeout_seconds,
        )
        return False

    async def release_migration_lock(self, conn: "asyncpg.Connection") -> None:
        """Release advisory lock after migration.

        Args:
            conn: Database connection that holds the lock

        Example:
            >>> await tracker.release_migration_lock(conn)
        """
        await conn.execute("SELECT pg_advisory_unlock($1)", self.ADVISORY_LOCK_ID)
        logger.debug("Migration advisory lock released")

    async def increment_version(
        self,
        table_name: str,
        new_dimension: Optional[int] = None,
        new_index_type: Optional[str] = None,
    ) -> int:
        """Increment schema version after successful migration.

        Updates schema_version, embedding_dimension, and/or index_type
        in the metadata table. Only call this after migration completes
        successfully.

        Args:
            table_name: Name of the table that was migrated
            new_dimension: New embedding dimension (if changed)
            new_index_type: New index type (if changed)

        Returns:
            New schema version number

        Example:
            >>> new_version = await tracker.increment_version(
            ...     "agv_v_chunks", new_dimension=1536
            ... )
            >>> print(f"Migrated to version {new_version}")
        """
        async with self._conn_manager.acquire() as conn:
            new_version = await conn.fetchval(
                f"""
                UPDATE {SCHEMA_META_TABLE}
                SET
                    schema_version = schema_version + 1,
                    embedding_dimension = COALESCE($2, embedding_dimension),
                    index_type = COALESCE($3, index_type),
                    updated_at = NOW()
                WHERE table_name = $1
                RETURNING schema_version
            """,
                table_name,
                new_dimension,
                new_index_type,
            )

            logger.info(
                "Schema version incremented: table=%s, version=%d",
                table_name,
                new_version,
            )
            return new_version

    async def register_table(
        self,
        table_name: str,
        embedding_dimension: int,
        index_type: str = "ivfflat",
    ) -> None:
        """Register a new table in schema metadata.

        Call this when creating a new table to initialize its metadata.

        Args:
            table_name: Name of the table to register
            embedding_dimension: Vector embedding dimension
            index_type: Type of index (hnsw, ivfflat, none)

        Example:
            >>> await tracker.register_table(
            ...     "agv_v_chunks", 768, "hnsw"
            ... )
        """
        async with self._conn_manager.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {SCHEMA_META_TABLE}
                    (table_name, schema_version, embedding_dimension, index_type)
                VALUES ($1, 1, $2, $3)
                ON CONFLICT (table_name) DO NOTHING
            """,
                table_name,
                embedding_dimension,
                index_type,
            )
        logger.info(
            "Table registered in schema metadata: %s (dim=%d, index=%s)",
            table_name,
            embedding_dimension,
            index_type,
        )
