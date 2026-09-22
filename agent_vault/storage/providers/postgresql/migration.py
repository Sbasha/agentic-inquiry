"""Schema migration support for PostgreSQL storage.

This module provides schema evolution capabilities including:
- Embedding dimension changes with backup creation (FR-3.1, FR-3.2)
- Backup verification (AC-18)
- Restore from backup
- Audit logging (SEC-2)

Design decisions:
    - Backup created before migration (safety first)
    - Row count verification required (AC-18)
    - Migration aborts if verification fails
    - All identifiers escaped for SQL injection prevention
    - Audit logging for all schema changes

Example:
    >>> migrator = SchemaMigrator(connection_manager, schema_tracker)
    >>> result = await migrator.migrate_dimension(
    ...     table_name="agv_chunks",
    ...     old_dimension=768,
    ...     new_dimension=1536
    ... )
    >>> print(result.backup_table_name, result.rows_affected)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from asyncpg.utils import _quote_ident as escape_identifier

if TYPE_CHECKING:
    from agent_vault.storage.providers.postgresql.connection import (
        PostgresConnectionManager,
    )
    from agent_vault.storage.providers.postgresql.schema_tracker import (
        SchemaVersionTracker,
    )

logger = logging.getLogger(__name__)


class MigrationError(Exception):
    """Raised when schema migration fails.

    This error is raised when:
    - Backup verification fails (row count mismatch)
    - Migration cannot be completed
    - Invalid migration parameters
    """

    pass


@dataclass
class MigrationResult:
    """Result of schema migration operation.

    Attributes:
        table_name: Name of migrated table
        backup_table_name: Name of backup table
        old_dimension: Previous embedding dimension
        new_dimension: New embedding dimension
        rows_affected: Number of rows in table
        backup_verified: Whether backup verification passed
        duration_seconds: Time taken for migration
        restore_command: Command to restore from backup
    """

    table_name: str
    backup_table_name: str
    old_dimension: int
    new_dimension: int
    rows_affected: int
    backup_verified: bool
    duration_seconds: float
    restore_command: str


class SchemaMigrator:
    """Service for schema evolution operations.

    Provides embedding dimension migration with backup creation,
    verification, and audit logging.

    Attributes:
        connection_manager: PostgreSQL connection pool manager
        schema_tracker: Schema version tracker for metadata
    """

    def __init__(
        self,
        connection_manager: PostgresConnectionManager,
        schema_tracker: SchemaVersionTracker,
    ):
        """Initialize schema migrator.

        Args:
            connection_manager: Connection pool manager for database access
            schema_tracker: Schema version tracker for metadata updates
        """
        self.connection_manager = connection_manager
        self.schema_tracker = schema_tracker

    async def migrate_dimension(
        self,
        table_name: str,
        column_name: str,
        new_dimension: int,
        backup_retention_days: int = 7,
        migration_lock_timeout: Optional[int] = None,
    ) -> MigrationResult:
        """Migrate embedding dimension with backup and verification.

        Implements FR-3.1, FR-3.2, AC-18:
        1. Create backup table (all columns except embedding)
        2. Verify backup row count matches source (AC-18)
        3. Abort if verification fails (AC-18)
        4. Drop and recreate embedding column
        5. Mark chunks for reindex
        6. Increment schema version
        7. Log audit events

        Args:
            table_name: Name of table to migrate
            column_name: Name of embedding column to change
            new_dimension: New embedding dimension
            backup_retention_days: Days to retain backup (default: 7)
            migration_lock_timeout: Timeout in seconds for acquiring advisory lock.
                If None, uses the default from config.storage.backend_timeouts.migration_lock_timeout
                (typically 30 seconds).

        Returns:
            MigrationResult with backup info and statistics

        Raises:
            MigrationError: If backup verification fails or migration cannot proceed

        Example:
            >>> result = await migrator.migrate_dimension(
            ...     table_name="agv_chunks",
            ...     column_name="embedding",
            ...     new_dimension=1536,
            ...     backup_retention_days=7
            ... )
            >>> if result.backup_verified:
            ...     print(f"Migration complete. Backup: {result.backup_table_name}")
        """
        start_time = time.monotonic()

        # Import audit logger
        from agent_vault.storage.audit import default_audit_logger

        # Escape identifiers for SQL injection prevention
        table_ident = escape_identifier(table_name)
        column_ident = escape_identifier(column_name)

        # Get connection for migration
        conn = await self.connection_manager.acquire_for_transaction()
        lock_acquired = False
        try:
            # Step 0: Acquire advisory lock to prevent concurrent migrations (AC-6)
            # Pass timeout if explicitly provided, otherwise use schema_tracker's default
            if migration_lock_timeout is not None:
                lock_acquired = await self.schema_tracker.acquire_migration_lock(
                    conn, timeout_seconds=migration_lock_timeout
                )
            else:
                lock_acquired = await self.schema_tracker.acquire_migration_lock(conn)
            if not lock_acquired:
                raise MigrationError(
                    "Cannot acquire migration lock. Another migration may be in progress. "
                    "Please wait for it to complete or check for hung migrations."
                )

            # Get current dimension
            # pgvector stores dimension directly in atttypmod (no header offset)
            current_dim_query = """
                SELECT atttypmod as dimension
                FROM pg_attribute
                WHERE attrelid = $1::regclass
                AND attname = $2
            """
            current_dim = await conn.fetchval(current_dim_query, table_name, column_name)

            if current_dim is None:
                raise MigrationError(
                    f"Column '{column_name}' not found in table '{table_name}'"
                )

            logger.info(
                f"Starting dimension migration: {table_name}.{column_name} "
                f"({current_dim} -> {new_dimension})"
            )

            # Log migration start
            default_audit_logger.log_migration_start(
                table_name=table_name,
                old_dimension=current_dim,
                new_dimension=new_dimension,
                metadata={"column_name": column_name},
            )

            # Step 1: Create backup table (AC-18)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_table_name = f"_agv_migration_backup_{table_name}_{timestamp}"
            backup_table_ident = escape_identifier(backup_table_name)

            # Get all columns except embedding
            columns_query = """
                SELECT column_name, data_type, character_maximum_length
                FROM information_schema.columns
                WHERE table_name = $1
                AND column_name != $2
                ORDER BY ordinal_position
            """
            columns = await conn.fetch(columns_query, table_name, column_name)

            # Build CREATE TABLE statement
            column_defs = []
            column_names = []
            for col in columns:
                col_name = col["column_name"]
                col_type = col["data_type"]
                if col["character_maximum_length"]:
                    col_type += f"({col['character_maximum_length']})"

                column_defs.append(f"{escape_identifier(col_name)} {col_type}")
                column_names.append(escape_identifier(col_name))

            create_backup_sql = f"""
                CREATE TABLE {backup_table_ident} (
                    {', '.join(column_defs)}
                )
            """
            await conn.execute(create_backup_sql)

            # Add comment with retention info
            from datetime import timedelta
            retention_date = datetime.now(timezone.utc) + timedelta(days=backup_retention_days)
            comment_sql = f"""
                COMMENT ON TABLE {backup_table_ident}
                IS 'Migration backup created at {timestamp}. Retention until {retention_date.strftime("%Y-%m-%d")}.'
            """
            await conn.execute(comment_sql)

            # Copy data to backup (excluding embedding column)
            copy_sql = f"""
                INSERT INTO {backup_table_ident} ({', '.join(column_names)})
                SELECT {', '.join(column_names)}
                FROM {table_ident}
            """
            await conn.execute(copy_sql)

            logger.info(f"Created backup table: {backup_table_name}")

            # Step 2: Verify backup row count (AC-18)
            source_count = await conn.fetchval(
                f"SELECT COUNT(*) FROM {table_ident}"
            )
            backup_count = await conn.fetchval(
                f"SELECT COUNT(*) FROM {backup_table_ident}"
            )

            if source_count != backup_count:
                # Critical failure - abort migration
                error_msg = (
                    f"Backup verification failed (AC-18): "
                    f"Source table has {source_count} rows, "
                    f"backup table has {backup_count} rows. "
                    f"Migration aborted."
                )
                logger.error(error_msg)

                # Log failure
                default_audit_logger.log_migration_failure(
                    table_name=table_name,
                    error=error_msg,
                )

                raise MigrationError(error_msg)

            logger.info(
                f"Backup verification passed: {source_count} rows matched (AC-18)"
            )

            # Step 3: Drop and recreate embedding column
            drop_column_sql = f"ALTER TABLE {table_ident} DROP COLUMN {column_ident}"
            await conn.execute(drop_column_sql)

            add_column_sql = f"""
                ALTER TABLE {table_ident}
                ADD COLUMN {column_ident} vector({new_dimension})
            """
            await conn.execute(add_column_sql)

            logger.info(
                f"Recreated column: {column_name} with dimension {new_dimension}"
            )

            # Step 4: Mark chunks for reindex (set needs_reindex flag if exists)
            try:
                mark_reindex_sql = f"""
                    UPDATE {table_ident}
                    SET needs_reindex = TRUE
                    WHERE needs_reindex IS NOT NULL
                """
                await conn.execute(mark_reindex_sql)
                logger.debug("Marked chunks for reindex")
            except Exception as e:
                # Column might not exist, that's OK
                logger.debug(f"Could not mark for reindex: {e}")

            # Step 5: Increment schema version
            await self.schema_tracker.increment_version(
                table_name=table_name,
                new_dimension=new_dimension,
            )

            duration = time.monotonic() - start_time

            # Step 6: Log migration success
            default_audit_logger.log_migration_success(
                table_name=table_name,
                old_dimension=current_dim,
                new_dimension=new_dimension,
                duration_seconds=duration,
                metadata={
                    "backup_table": backup_table_name,
                    "rows_affected": source_count,
                },
            )

            # Generate restore command
            restore_command = (
                f"agv schema restore --project <project> "
                f"--backup {backup_table_name}"
            )

            result = MigrationResult(
                table_name=table_name,
                backup_table_name=backup_table_name,
                old_dimension=current_dim,
                new_dimension=new_dimension,
                rows_affected=source_count,
                backup_verified=True,
                duration_seconds=duration,
                restore_command=restore_command,
            )

            logger.info(
                f"Dimension migration complete: {table_name} "
                f"({current_dim} -> {new_dimension}, {source_count} rows, "
                f"{duration:.2f}s)"
            )

            return result

        except Exception as e:
            # Log failure
            logger.error(f"Migration failed: {e}")
            default_audit_logger.log_migration_failure(
                table_name=table_name,
                error=str(e),
            )
            raise

        finally:
            # Release advisory lock if acquired
            if lock_acquired:
                try:
                    await self.schema_tracker.release_migration_lock(conn)
                except Exception as lock_error:
                    logger.warning(f"Failed to release migration lock: {lock_error}")
            await self.connection_manager.release_transaction_connection(conn)

    async def restore_from_backup(
        self,
        table_name: str,
        backup_table_name: str,
    ) -> int:
        """Restore table from backup.

        Restores non-embedding columns from backup table. Embedding column
        remains empty (requires re-indexing).

        Args:
            table_name: Name of table to restore
            backup_table_name: Name of backup table

        Returns:
            Number of rows restored

        Raises:
            MigrationError: If backup table doesn't exist or restore fails

        Example:
            >>> rows = await migrator.restore_from_backup(
            ...     table_name="agv_chunks",
            ...     backup_table_name="_agv_migration_backup_agv_chunks_20260113_123456"
            ... )
        """
        from agent_vault.storage.audit import default_audit_logger

        table_ident = escape_identifier(table_name)
        backup_table_ident = escape_identifier(backup_table_name)

        conn = await self.connection_manager.acquire_for_transaction()
        try:
            # Verify backup table exists
            exists = await conn.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = $1
                )
                """,
                backup_table_name,
            )

            if not exists:
                raise MigrationError(
                    f"Backup table '{backup_table_name}' not found. "
                    f"Cannot restore."
                )

            # Get column names from backup table
            columns = await conn.fetch(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = $1
                ORDER BY ordinal_position
                """,
                backup_table_name,
            )

            column_names = [escape_identifier(col["column_name"]) for col in columns]

            # Clear current table (keep structure)
            await conn.execute(f"TRUNCATE TABLE {table_ident}")

            # Restore data from backup
            restore_sql = f"""
                INSERT INTO {table_ident} ({', '.join(column_names)})
                SELECT {', '.join(column_names)}
                FROM {backup_table_ident}
            """
            await conn.execute(restore_sql)

            # Get row count
            row_count = await conn.fetchval(
                f"SELECT COUNT(*) FROM {table_ident}"
            )

            logger.info(
                f"Restored {row_count} rows from backup: {backup_table_name}"
            )

            # Log restore
            default_audit_logger.log_backup_restored(
                table_name=table_name,
                backup_table=backup_table_name,
                rows_restored=row_count,
            )

            return row_count

        finally:
            await self.connection_manager.release_transaction_connection(conn)

    async def list_backups(self, table_name: Optional[str] = None) -> list[dict[str, Any]]:
        """List available migration backup tables.

        Args:
            table_name: Optional filter by source table name

        Returns:
            List of backup table info dictionaries

        Example:
            >>> backups = await migrator.list_backups("agv_chunks")
            >>> for backup in backups:
            ...     print(backup["backup_table"], backup["created_at"])
        """
        conn = await self.connection_manager.acquire_for_transaction()
        try:
            if table_name:
                # Use parameterized query to prevent SQL injection
                query = """
                    SELECT
                        tablename as backup_table,
                        obj_description(tablename::regclass) as comment
                    FROM pg_tables
                    WHERE schemaname = 'public'
                    AND tablename LIKE '_agv_migration_backup_%'
                    AND tablename LIKE '_agv_migration_backup_' || $1 || '_%'
                """
                rows = await conn.fetch(query, table_name)
            else:
                query = """
                    SELECT
                        tablename as backup_table,
                        obj_description(tablename::regclass) as comment
                    FROM pg_tables
                    WHERE schemaname = 'public'
                    AND tablename LIKE '_agv_migration_backup_%'
                """
                rows = await conn.fetch(query)

            backups = []
            for row in rows:
                backup_info = {
                    "backup_table": row["backup_table"],
                    "comment": row["comment"],
                }
                backups.append(backup_info)

            return backups

        finally:
            await self.connection_manager.release_transaction_connection(conn)

    async def cleanup_expired_backups(self) -> int:
        """Delete backup tables past their retention date.

        Returns:
            Number of backup tables deleted

        Example:
            >>> deleted = await migrator.cleanup_expired_backups()
            >>> print(f"Deleted {deleted} expired backups")
        """
        from agent_vault.storage.audit import default_audit_logger

        conn = await self.connection_manager.acquire_for_transaction()
        try:
            # Get all backup tables with retention info
            backups_query = """
                SELECT
                    tablename,
                    obj_description(tablename::regclass) as comment
                FROM pg_tables
                WHERE schemaname = 'public'
                AND tablename LIKE '_agv_migration_backup_%'
            """
            backups = await conn.fetch(backups_query)

            deleted_count = 0
            for backup in backups:
                table_name = backup["tablename"]
                comment = backup["comment"] or ""

                # Parse retention date from comment
                # Format: "... Retention until YYYY-MM-DD."
                if "Retention until" in comment:
                    try:
                        retention_str = comment.split("Retention until ")[1].split(".")[0]
                        retention_date = datetime.strptime(retention_str, "%Y-%m-%d")
                        retention_date = retention_date.replace(tzinfo=timezone.utc)

                        # Check if expired
                        if datetime.now(timezone.utc) > retention_date:
                            table_ident = escape_identifier(table_name)
                            await conn.execute(f"DROP TABLE {table_ident}")
                            deleted_count += 1

                            logger.info(f"Deleted expired backup: {table_name}")

                            # Log cleanup
                            default_audit_logger.log_backup_deleted(
                                backup_table=table_name,
                                reason="expired",
                            )

                    except Exception as e:
                        logger.warning(
                            f"Could not parse retention date for {table_name}: {e}"
                        )

            return deleted_count

        finally:
            await self.connection_manager.release_transaction_connection(conn)
