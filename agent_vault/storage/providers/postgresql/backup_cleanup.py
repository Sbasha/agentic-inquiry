"""Backup cleanup for old migration backups.

This module provides cleanup operations for migration backups that have
exceeded their retention period. Implements T4.7 for automatic backup
maintenance.

Design decisions:
    - Identifies backups by table name pattern
    - Checks retention period from table comment metadata
    - Deletes backups past retention date
    - Logs all cleanup actions
    - Integrates with maintenance operations

Example:
    >>> cleaner = BackupCleaner(connection_manager)
    >>> result = await cleaner.cleanup_expired_backups(dry_run=False)
    >>> print(f"Deleted {result['deleted_count']} expired backups")
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from asyncpg.utils import _quote_ident as escape_identifier

if TYPE_CHECKING:
    import asyncpg

    from agent_vault.storage.providers.postgresql.connection import (
        PostgresConnectionManager,
    )

logger = logging.getLogger(__name__)


@dataclass
class BackupInfo:
    """Information about a migration backup table.

    Attributes:
        table_name: Full backup table name
        source_table: Original table name
        timestamp: Backup creation timestamp
        retention_days: Retention period in days
        row_count: Number of rows in backup
        size_bytes: Table size in bytes
        created_at: Actual creation timestamp from database
    """

    table_name: str
    source_table: str
    timestamp: str
    retention_days: int
    row_count: int
    size_bytes: int
    created_at: datetime


@dataclass
class CleanupResult:
    """Result of backup cleanup operation.

    Attributes:
        scanned_count: Number of backups scanned
        expired_count: Number of expired backups found
        deleted_count: Number of backups deleted
        freed_bytes: Total bytes freed by cleanup
        duration_seconds: Time taken for cleanup
        dry_run: Whether this was a dry run
        deleted_tables: List of table names that were deleted
    """

    scanned_count: int
    expired_count: int
    deleted_count: int
    freed_bytes: int
    duration_seconds: float
    dry_run: bool
    deleted_tables: list[str]


class BackupCleaner:
    """Service for cleaning up expired migration backups.

    Implements T4.7: Add Backup Cleanup Job for maintenance operations.

    This class provides automated cleanup of migration backup tables that
    have exceeded their retention period.
    """

    # Pattern for backup table names: _agv_migration_backup_<table>_<timestamp>
    BACKUP_TABLE_PATTERN = re.compile(r"^_agv_migration_backup_(.+)_(\d{8}_\d{6})$")

    def __init__(self, connection_manager: PostgresConnectionManager):
        """Initialize backup cleaner.

        Args:
            connection_manager: PostgreSQL connection pool manager
        """
        self._conn_manager = connection_manager

    async def cleanup_expired_backups(
        self,
        dry_run: bool = True,
        max_backups_to_delete: int = 100,
    ) -> CleanupResult:
        """Clean up expired migration backup tables.

        Scans for backup tables, checks retention periods, and deletes
        expired backups.

        Args:
            dry_run: If True, return what would be deleted without deleting
            max_backups_to_delete: Safety limit on deletions per run

        Returns:
            CleanupResult with statistics

        Example:
            >>> # Preview cleanup
            >>> result = await cleaner.cleanup_expired_backups(dry_run=True)
            >>> print(f"Would delete {result.expired_count} backups")
            >>>
            >>> # Actually delete
            >>> result = await cleaner.cleanup_expired_backups(dry_run=False)
            >>> print(f"Deleted {result.deleted_count} backups, freed {result.freed_bytes} bytes")
        """
        start_time = time.monotonic()

        conn = await self._conn_manager.acquire_for_transaction()
        try:
            # Find all backup tables
            backup_tables = await self._find_backup_tables(conn)

            logger.info(f"Found {len(backup_tables)} backup tables to scan")

            # Determine which are expired
            now = datetime.now(timezone.utc)
            expired_backups = []

            for backup in backup_tables:
                expiration_date = backup.created_at + timedelta(days=backup.retention_days)
                if now > expiration_date:
                    expired_backups.append(backup)
                    logger.debug(
                        f"Backup {backup.table_name} expired "
                        f"(created: {backup.created_at}, retention: {backup.retention_days} days)"
                    )

            if not expired_backups:
                logger.info("No expired backups found")
                return CleanupResult(
                    scanned_count=len(backup_tables),
                    expired_count=0,
                    deleted_count=0,
                    freed_bytes=0,
                    duration_seconds=time.monotonic() - start_time,
                    dry_run=dry_run,
                    deleted_tables=[],
                )

            # Limit deletions for safety
            backups_to_delete = expired_backups[:max_backups_to_delete]

            if dry_run:
                total_bytes = sum(b.size_bytes for b in backups_to_delete)
                logger.info(
                    f"Dry-run: would delete {len(backups_to_delete)} expired backups "
                    f"({total_bytes / (1024**2):.2f} MB)"
                )
                return CleanupResult(
                    scanned_count=len(backup_tables),
                    expired_count=len(expired_backups),
                    deleted_count=len(backups_to_delete),
                    freed_bytes=total_bytes,
                    duration_seconds=time.monotonic() - start_time,
                    dry_run=True,
                    deleted_tables=[b.table_name for b in backups_to_delete],
                )

            # Actually delete backups
            deleted_count = 0
            freed_bytes = 0
            deleted_tables = []

            for backup in backups_to_delete:
                try:
                    # Escape table name to prevent SQL injection
                    safe_table = escape_identifier(backup.table_name)
                    await conn.execute(f"DROP TABLE IF EXISTS {safe_table}")

                    deleted_count += 1
                    freed_bytes += backup.size_bytes
                    deleted_tables.append(backup.table_name)

                    logger.info(
                        f"Deleted expired backup: {backup.table_name} "
                        f"({backup.size_bytes / (1024**2):.2f} MB, "
                        f"{backup.retention_days} day retention)"
                    )

                except Exception as e:
                    logger.error(f"Failed to delete backup {backup.table_name}: {e}")

            logger.info(
                f"Cleanup complete: deleted {deleted_count} backups, "
                f"freed {freed_bytes / (1024**2):.2f} MB"
            )

            return CleanupResult(
                scanned_count=len(backup_tables),
                expired_count=len(expired_backups),
                deleted_count=deleted_count,
                freed_bytes=freed_bytes,
                duration_seconds=time.monotonic() - start_time,
                dry_run=False,
                deleted_tables=deleted_tables,
            )

        finally:
            await self._conn_manager.release_transaction_connection(conn)

    async def list_backups(self) -> list[BackupInfo]:
        """List all migration backup tables.

        Returns:
            List of BackupInfo for all backup tables

        Example:
            >>> backups = await cleaner.list_backups()
            >>> for backup in backups:
            ...     print(f"{backup.table_name}: {backup.row_count} rows, "
            ...           f"{backup.retention_days} days retention")
        """
        conn = await self._conn_manager.acquire_for_transaction()
        try:
            return await self._find_backup_tables(conn)
        finally:
            await self._conn_manager.release_transaction_connection(conn)

    async def _find_backup_tables(self, conn: asyncpg.Connection) -> list[BackupInfo]:
        """Find all migration backup tables.

        Args:
            conn: Database connection

        Returns:
            List of BackupInfo for all backup tables found
        """
        # Query for backup tables
        query = """
            SELECT
                c.relname as table_name,
                pg_total_relation_size(c.oid) as size_bytes,
                pg_stat_get_live_tuples(c.oid) as row_count,
                obj_description(c.oid) as table_comment,
                (SELECT creation_time FROM pg_stat_file(
                    pg_relation_filepath(c.oid)
                )) as created_at
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
              AND c.relname LIKE '_agv_migration_backup_%'
            ORDER BY c.relname
        """

        rows = await conn.fetch(query)

        backups = []
        for row in rows:
            table_name = row["table_name"]

            # Parse table name
            match = self.BACKUP_TABLE_PATTERN.match(table_name)
            if not match:
                logger.warning(f"Backup table {table_name} doesn't match expected pattern")
                continue

            source_table = match.group(1)
            timestamp = match.group(2)

            # Parse retention from table comment
            retention_days = 7  # Default
            if row["table_comment"]:
                # Look for "retention:<days>" in comment
                retention_match = re.search(r"retention:(\d+)", row["table_comment"])
                if retention_match:
                    retention_days = int(retention_match.group(1))

            backups.append(
                BackupInfo(
                    table_name=table_name,
                    source_table=source_table,
                    timestamp=timestamp,
                    retention_days=retention_days,
                    row_count=row["row_count"] or 0,
                    size_bytes=row["size_bytes"] or 0,
                    created_at=row["created_at"] or datetime.now(timezone.utc),
                )
            )

        return backups

    async def get_backup_info(self, backup_table_name: str) -> BackupInfo | None:
        """Get information about a specific backup table.

        Args:
            backup_table_name: Name of backup table

        Returns:
            BackupInfo if table exists, None otherwise

        Example:
            >>> info = await cleaner.get_backup_info(
            ...     "_agv_migration_backup_agv_v_chunks_20260113_120000"
            ... )
            >>> if info:
            ...     print(f"Backup has {info.row_count} rows")
        """
        conn = await self._conn_manager.acquire_for_transaction()
        try:
            backups = await self._find_backup_tables(conn)
            for backup in backups:
                if backup.table_name == backup_table_name:
                    return backup
            return None
        finally:
            await self._conn_manager.release_transaction_connection(conn)

    async def delete_backup(self, backup_table_name: str) -> bool:
        """Delete a specific backup table.

        Args:
            backup_table_name: Name of backup table to delete

        Returns:
            True if deleted, False if not found

        Raises:
            Exception: If deletion fails

        Example:
            >>> success = await cleaner.delete_backup(
            ...     "_agv_migration_backup_agv_v_chunks_20260113_120000"
            ... )
            >>> print(f"Deleted: {success}")
        """
        conn = await self._conn_manager.acquire_for_transaction()
        try:
            # Check if table exists
            exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = $1
                )
                """,
                backup_table_name,
            )

            if not exists:
                logger.warning(f"Backup table {backup_table_name} not found")
                return False

            # Escape table name and delete
            safe_table = escape_identifier(backup_table_name)
            await conn.execute(f"DROP TABLE {safe_table}")

            logger.info(f"Deleted backup table: {backup_table_name}")
            return True

        finally:
            await self._conn_manager.release_transaction_connection(conn)
