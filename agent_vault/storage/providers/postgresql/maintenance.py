"""PostgreSQL maintenance operations for index rebuild and vacuum.

This module provides maintenance operations for PostgreSQL storage:
- Index rebuild with CONCURRENTLY (FR-1.4)
- VACUUM ANALYZE operations (FR-6.3)
- Transaction context detection (AC-15)

Design decisions:
    - CONCURRENTLY prevents table locks during rebuild
    - Transaction context detection prevents PostgreSQL errors
    - All identifiers escaped for SQL injection prevention
    - Statistics returned for observability

Example:
    >>> service = PostgresMaintenanceService(connection_manager)
    >>> result = await service.rebuild_index(
    ...     table_name="agv_chunks",
    ...     index_name="idx_chunks_embedding",
    ...     index_type="hnsw"
    ... )
    >>> print(result.duration_seconds, result.rows_indexed)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from asyncpg.utils import _quote_ident as escape_identifier

if TYPE_CHECKING:
    import asyncpg

    from agent_vault.storage.providers.postgresql.connection import (
        PostgresConnectionManager,
    )
    from agent_vault.storage.providers.postgresql.index_config import (
        IndexConfig,
    )

logger = logging.getLogger(__name__)


class IndexRebuildError(Exception):
    """Raised when index rebuild cannot proceed.

    This error is raised when:
    - Rebuild called within a transaction context (PostgreSQL limitation)
    - Index name conflicts or doesn't exist
    - Invalid index configuration
    """

    pass


@dataclass
class IndexRebuildResult:
    """Result of index rebuild operation.

    Attributes:
        index_name: Name of the rebuilt index
        old_index_name: Name of the old index (before rebuild)
        duration_seconds: Time taken for rebuild
        rows_indexed: Number of rows indexed
        index_type: Type of index (hnsw, ivfflat)
        index_size_bytes: Size of the new index in bytes
    """

    index_name: str
    old_index_name: str
    duration_seconds: float
    rows_indexed: int
    index_type: str
    index_size_bytes: int


@dataclass
class MaintenanceResult:
    """Result of maintenance operation.

    Attributes:
        operation: Type of operation (vacuum, reindex)
        table_name: Name of table operated on
        duration_seconds: Time taken
        statistics: Operation-specific statistics
    """

    operation: str
    table_name: str
    duration_seconds: float
    statistics: dict[str, Any]


class PostgresMaintenanceService:
    """Service for PostgreSQL maintenance operations.

    Provides index rebuild, vacuum, and reindex operations with proper
    safety checks and transaction context detection.

    Attributes:
        connection_manager: PostgreSQL connection pool manager
    """

    def __init__(self, connection_manager: PostgresConnectionManager):
        """Initialize maintenance service.

        Args:
            connection_manager: Connection pool manager for database access.
                Its ``similarity_metric`` is read once here and used for
                rebuild DDL so that a database configured with l2 or dot
                does not get a silently-cosine op-class on index rebuild.
        """
        self.connection_manager = connection_manager
        self._similarity_metric = connection_manager.similarity_metric

    async def rebuild_index(
        self,
        table_name: str,
        column_name: str,
        index_config: IndexConfig,
        old_index_name: str | None = None,
    ) -> IndexRebuildResult:
        """Rebuild vector index with CONCURRENTLY option.

        Implements FR-1.4: Index migration with no table lock.

        This method:
        1. Checks for transaction context (raises IndexRebuildError if in transaction)
        2. Creates new index with CONCURRENTLY (no table lock)
        3. Drops old index after new index is ready
        4. Returns rebuild statistics

        Args:
            table_name: Name of table containing vector column
            column_name: Name of vector column to index
            index_config: Index configuration (type, parameters)
            old_index_name: Name of existing index to replace (optional)

        Returns:
            IndexRebuildResult with statistics

        Raises:
            IndexRebuildError: If called within transaction or rebuild fails

        Example:
            >>> from agent_vault.storage.providers.postgresql.index_config import (
            ...     IndexConfig, IndexType, HNSWParams
            ... )
            >>> config = IndexConfig(
            ...     index_type=IndexType.HNSW,
            ...     hnsw_params=HNSWParams(m=16, ef_construction=64)
            ... )
            >>> result = await service.rebuild_index(
            ...     table_name="agv_chunks",
            ...     column_name="embedding",
            ...     index_config=config,
            ...     old_index_name="idx_chunks_embedding_old"
            ... )
        """
        start_time = time.monotonic()

        # Generate new index name
        new_index_name = f"idx_{table_name}_{column_name}_new"
        if not old_index_name:
            old_index_name = f"idx_{table_name}_{column_name}"

        # Escape identifiers for SQL injection prevention
        table_ident = escape_identifier(table_name)
        new_index_ident = escape_identifier(new_index_name)
        old_index_ident = escape_identifier(old_index_name)

        logger.info(
            f"Starting index rebuild: {table_name}.{column_name} "
            f"(type={index_config.index_type})"
        )

        # Get connection - must be outside transaction for CONCURRENTLY
        conn = await self.connection_manager.acquire_for_transaction()
        try:
            # AC-15: Check for transaction context on THIS connection
            if await self._is_in_transaction(conn):
                raise IndexRebuildError(
                    "Index rebuild cannot run inside a transaction. "
                    "Call rebuild_index() outside transaction context. "
                    "Reason: CREATE INDEX CONCURRENTLY cannot run in a transaction block."
                )
            # Get row count before rebuild
            count_query = f"SELECT COUNT(*) FROM {table_ident}"
            row_count = await conn.fetchval(count_query)

            # Generate index creation SQL
            from agent_vault.storage.providers.postgresql.schemas import (
                SchemaGenerator,
            )

            generator = SchemaGenerator(similarity_metric=self._similarity_metric)
            index_sql = generator.generate_vector_index(
                table_name=table_name,
                column_name=column_name,
                index_config=index_config,
            )

            if not index_sql:
                raise IndexRebuildError(
                    f"Cannot generate index SQL for type: {index_config.index_type}"
                )

            # Replace index name in generated SQL to use new_index_name
            index_sql = index_sql.replace(
                escape_identifier(old_index_name), new_index_ident
            )

            # Add CONCURRENTLY keyword (must be outside transaction)
            index_sql = index_sql.replace("CREATE INDEX", "CREATE INDEX CONCURRENTLY")

            # Create new index
            logger.debug(f"Executing: {index_sql}")
            await conn.execute(index_sql)

            # Get new index size
            size_query = f"""
                SELECT pg_total_relation_size({new_index_ident!r}::regclass)
            """
            index_size = await conn.fetchval(size_query)

            # Drop old index if it exists
            drop_sql = f"DROP INDEX CONCURRENTLY IF EXISTS {old_index_ident}"
            logger.debug(f"Executing: {drop_sql}")
            await conn.execute(drop_sql)

            # Rename new index to old index name
            rename_sql = f"ALTER INDEX {new_index_ident} RENAME TO {old_index_ident}"
            logger.debug(f"Executing: {rename_sql}")
            await conn.execute(rename_sql)

            duration = time.monotonic() - start_time

            result = IndexRebuildResult(
                index_name=old_index_name,
                old_index_name=old_index_name,
                duration_seconds=duration,
                rows_indexed=row_count,
                index_type=index_config.index_type.value,
                index_size_bytes=index_size or 0,
            )

            logger.info(
                f"Index rebuild complete: {old_index_name} "
                f"({row_count} rows, {duration:.2f}s, "
                f"{index_size / (1024**2):.2f} MB)"
            )

            return result

        finally:
            await self.connection_manager.release_transaction_connection(conn)

    async def _is_in_transaction(self, conn: "asyncpg.Connection") -> bool:
        """Check if the given connection is in a transaction context.

        Args:
            conn: The database connection to check

        Returns:
            True if in transaction, False otherwise
        """
        # Check if transaction is active on this connection
        # pg_current_xact_id_if_assigned() returns NULL if not in a transaction
        transaction_status = await conn.fetchval(
            "SELECT CASE "
            "WHEN pg_current_xact_id_if_assigned() IS NULL THEN false "
            "ELSE true END"
        )
        return bool(transaction_status)

    async def run_maintenance(
        self,
        operation: Literal["vacuum", "reindex"],
        table_name: str,
    ) -> MaintenanceResult:
        """Run maintenance operation on table.

        Implements FR-6: Maintenance operations.

        Args:
            operation: Type of operation ("vacuum" or "reindex")
            table_name: Name of table to maintain

        Returns:
            MaintenanceResult with statistics

        Example:
            >>> result = await service.run_maintenance("vacuum", "agv_chunks")
            >>> print(result.statistics)
        """
        start_time = time.monotonic()

        if operation == "vacuum":
            stats = await self._vacuum_table(table_name)
        elif operation == "reindex":
            stats = await self._reindex_table(table_name)
        else:
            raise ValueError(f"Unknown maintenance operation: {operation}")

        duration = time.monotonic() - start_time

        return MaintenanceResult(
            operation=operation,
            table_name=table_name,
            duration_seconds=duration,
            statistics=stats,
        )

    async def _vacuum_table(self, table_name: str) -> dict[str, Any]:
        """Execute VACUUM ANALYZE on table.

        Args:
            table_name: Name of table to vacuum

        Returns:
            Statistics dictionary
        """
        table_ident = escape_identifier(table_name)

        conn = await self.connection_manager.acquire_for_transaction()
        try:
            # Get dead tuples before vacuum
            stats_before = await conn.fetchrow(
                """
                SELECT n_dead_tup, n_live_tup
                FROM pg_stat_user_tables
                WHERE schemaname = 'public' AND relname = $1
                """,
                table_name,
            )

            # Run VACUUM ANALYZE
            vacuum_sql = f"VACUUM ANALYZE {table_ident}"
            logger.debug(f"Executing: {vacuum_sql}")
            await conn.execute(vacuum_sql)

            # Get stats after vacuum
            stats_after = await conn.fetchrow(
                """
                SELECT n_dead_tup, n_live_tup
                FROM pg_stat_user_tables
                WHERE schemaname = 'public' AND relname = $1
                """,
                table_name,
            )

            return {
                "dead_tuples_before": stats_before["n_dead_tup"] if stats_before else 0,
                "dead_tuples_after": stats_after["n_dead_tup"] if stats_after else 0,
                "live_tuples": stats_after["n_live_tup"] if stats_after else 0,
            }

        finally:
            await self.connection_manager.release_transaction_connection(conn)

    async def _reindex_table(self, table_name: str) -> dict[str, Any]:
        """Reindex all indexes on table.

        Args:
            table_name: Name of table to reindex

        Returns:
            Statistics dictionary
        """
        table_ident = escape_identifier(table_name)

        conn = await self.connection_manager.acquire_for_transaction()
        try:
            # Get index count
            index_count = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = $1
                """,
                table_name,
            )

            # Reindex table
            reindex_sql = f"REINDEX TABLE {table_ident}"
            logger.debug(f"Executing: {reindex_sql}")
            await conn.execute(reindex_sql)

            return {
                "indexes_rebuilt": index_count or 0,
            }

        finally:
            await self.connection_manager.release_transaction_connection(conn)

    async def get_maintenance_status(self, table_name: str) -> dict[str, Any]:
        """Get maintenance status for table.

        Args:
            table_name: Name of table to check

        Returns:
            Status dictionary with index info and table statistics
        """
        conn = await self.connection_manager.acquire_for_transaction()
        try:
            # Get table statistics
            table_stats = await conn.fetchrow(
                """
                SELECT
                    n_live_tup,
                    n_dead_tup,
                    last_vacuum,
                    last_autovacuum,
                    last_analyze,
                    last_autoanalyze
                FROM pg_stat_user_tables
                WHERE schemaname = 'public' AND relname = $1
                """,
                table_name,
            )

            # Get index information
            indexes = await conn.fetch(
                """
                SELECT
                    indexname,
                    indexdef,
                    pg_total_relation_size(indexname::regclass) as index_size
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = $1
                """,
                table_name,
            )

            return {
                "table_stats": dict(table_stats) if table_stats else {},
                "indexes": [
                    {
                        "name": idx["indexname"],
                        "definition": idx["indexdef"],
                        "size_bytes": idx["index_size"],
                    }
                    for idx in indexes
                ],
            }

        finally:
            await self.connection_manager.release_transaction_connection(conn)
