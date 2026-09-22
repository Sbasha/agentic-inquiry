"""CLI commands for schema migration.

Provides `agv schema migrate` and `agv schema restore` commands for managing
embedding dimension changes with backup/restore capabilities.

Usage:
    # Migrate to new dimension (requires --confirm-data-loss)
    agv schema migrate --project my_project --new-dimension 1536 --confirm-data-loss

    # Preview migration without executing
    agv schema migrate --project my_project --new-dimension 1536 --dry-run

    # Set backup retention period
    agv schema migrate --project my_project --new-dimension 1536 \\
        --confirm-data-loss --backup-retention-days 14

    # Restore from backup
    agv schema restore --project my_project --backup-timestamp 20260113_132045
"""

import asyncio
import logging
import sys
from typing import Optional

import click

from agent_vault.storage.providers.postgresql.connection import (
    PostgresConnectionManager,
)
from agent_vault.storage.providers.postgresql.migration import SchemaMigrator
from agent_vault.storage.providers.postgresql.schema_tracker import (
    SchemaVersionTracker,
)

logger = logging.getLogger(__name__)


@click.group()
def schema():
    """Schema management commands."""
    pass


@schema.command("migrate")
@click.option(
    "--project",
    required=True,
    help="Project ID to migrate schema for",
)
@click.option(
    "--new-dimension",
    type=int,
    required=True,
    help="New embedding dimension (e.g., 768, 1536, 3072)",
)
@click.option(
    "--table",
    default="agv_v_chunks",
    help="Table name to migrate (default: agv_v_chunks)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show migration plan without executing",
)
@click.option(
    "--confirm-data-loss",
    is_flag=True,
    help="Required flag to confirm you understand embeddings will be deleted",
)
@click.option(
    "--backup-retention-days",
    type=int,
    default=7,
    help="Number of days to retain backup before cleanup (default: 7)",
)
@click.option(
    "--connection-string",
    envvar="agv_CONNECTION_STRING",
    help="PostgreSQL connection string (or set agv_CONNECTION_STRING env var)",
)
def migrate(
    project: str,
    new_dimension: int,
    table: str,
    dry_run: bool,
    confirm_data_loss: bool,
    backup_retention_days: int,
    connection_string: Optional[str],
):
    """Migrate embedding dimension for a table.

    This operation:
    1. Creates a backup of all data (excluding embeddings)
    2. Verifies backup row count matches source
    3. Drops and recreates the embedding column
    4. Marks all chunks for re-indexing
    5. Recreates the index (empty)

    WARNING: All existing embeddings will be lost. You must re-index all content
    after migration completes.

    Examples:

        # Preview migration
        agv schema migrate --project my_project --new-dimension 1536 --dry-run

        # Execute migration (requires confirmation)
        agv schema migrate --project my_project --new-dimension 1536 --confirm-data-loss

        # Extended backup retention
        agv schema migrate --project my_project --new-dimension 1536 \\
            --confirm-data-loss --backup-retention-days 14
    """
    asyncio.run(
        _run_migrate(
            project=project,
            new_dimension=new_dimension,
            table=table,
            dry_run=dry_run,
            confirm_data_loss=confirm_data_loss,
            backup_retention_days=backup_retention_days,
            connection_string=connection_string,
        )
    )


@schema.command("list-backups")
@click.option(
    "--connection-string",
    envvar="agv_CONNECTION_STRING",
    help="PostgreSQL connection string (or set agv_CONNECTION_STRING env var)",
)
@click.option(
    "--table",
    default=None,
    help="Filter backups for a specific table (default: show all)",
)
def list_backups(
    connection_string: Optional[str],
    table: Optional[str],
):
    """List available migration backups.

    Shows all backup tables created during schema migrations, including
    their timestamps, row counts, and associated source tables.

    Examples:

        # List all backups
        agv schema list-backups

        # List backups for a specific table
        agv schema list-backups --table agv_v_chunks
    """
    asyncio.run(_run_list_backups(connection_string, table))


@schema.command("restore")
@click.option(
    "--project",
    required=True,
    help="Project ID to restore schema for",
)
@click.option(
    "--backup-timestamp",
    required=True,
    help="Backup timestamp to restore from (format: YYYYMMDD_HHMMSS)",
)
@click.option(
    "--table",
    default="agv_v_chunks",
    help="Table name to restore (default: agv_v_chunks)",
)
@click.option(
    "--connection-string",
    envvar="agv_CONNECTION_STRING",
    help="PostgreSQL connection string (or set agv_CONNECTION_STRING env var)",
)
def restore(
    project: str,
    backup_timestamp: str,
    table: str,
    connection_string: Optional[str],
):
    """Restore from migration backup.

    This command restores data from a backup created during schema migration.
    It will drop the current table and restore from the backup.

    WARNING: This will overwrite the current table with backup data.

    Examples:

        # Restore from backup
        agv schema restore --project my_project --backup-timestamp 20260113_132045

        # Restore different table
        agv schema restore --project my_project --backup-timestamp 20260113_132045 \\
            --table agv_v_chunks_custom
    """
    asyncio.run(
        _run_restore(
            project=project,
            backup_timestamp=backup_timestamp,
            table=table,
            connection_string=connection_string,
        )
    )


async def _run_list_backups(
    connection_string: Optional[str],
    table_filter: Optional[str],
):
    """List available migration backups.

    Args:
        connection_string: Database connection string
        table_filter: Optional table name to filter backups
    """
    if not connection_string:
        click.echo(
            "Error: Connection string required. "
            "Provide via --connection-string or agv_CONNECTION_STRING env var.",
            err=True,
        )
        sys.exit(1)

    # Initialize connection manager
    conn_manager = PostgresConnectionManager(connection_string=connection_string)
    await conn_manager.initialize()

    try:
        async with conn_manager.acquire() as conn:
            # Query for backup tables
            query = """
                SELECT
                    table_name,
                    pg_total_relation_size(quote_ident(table_name)) as size_bytes
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name LIKE '_agv_migration_backup_%'
                ORDER BY table_name DESC
            """
            rows = await conn.fetch(query)

            if not rows:
                click.echo("No backup tables found.")
                return

            # Filter by table if specified
            filtered_rows = []
            for row in rows:
                table_name = row["table_name"]
                # Parse table name: _agv_migration_backup_{source_table}_{timestamp}
                if table_filter:
                    if f"_agv_migration_backup_{table_filter}_" not in table_name:
                        continue
                filtered_rows.append(row)

            if not filtered_rows:
                click.echo(f"No backup tables found for table '{table_filter}'.")
                return

            # Display results
            click.echo("=" * 80)
            click.echo("AVAILABLE MIGRATION BACKUPS")
            click.echo("=" * 80)
            click.echo(f"{'Backup Table':<55} {'Size':>10} {'Rows':>10}")
            click.echo("-" * 80)

            for row in filtered_rows:
                table_name = row["table_name"]
                size_bytes = row["size_bytes"]

                # Get row count
                from asyncpg.utils import _quote_ident as escape_identifier

                safe_table = escape_identifier(table_name)
                row_count = await conn.fetchval(f"SELECT COUNT(*) FROM {safe_table}")

                # Format size
                if size_bytes < 1024:
                    size_str = f"{size_bytes} B"
                elif size_bytes < 1024 * 1024:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                elif size_bytes < 1024 * 1024 * 1024:
                    size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                else:
                    size_str = f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

                click.echo(f"{table_name:<55} {size_str:>10} {row_count:>10,}")

            click.echo("-" * 80)
            click.echo(f"Total: {len(filtered_rows)} backup(s)")
            click.echo("=" * 80)
            click.echo("\nTo restore from a backup, use:")
            click.echo("  agv schema restore --project <project> --backup-timestamp <timestamp>")

    except Exception as e:
        click.echo(f"\nError listing backups: {e}", err=True)
        logger.exception("Failed to list backups")
        sys.exit(1)

    finally:
        await conn_manager.close()


async def _run_migrate(
    project: str,
    new_dimension: int,
    table: str,
    dry_run: bool,
    confirm_data_loss: bool,
    backup_retention_days: int,
    connection_string: Optional[str],
):
    """Execute schema migration.

    Args:
        project: Project ID
        new_dimension: New embedding dimension
        table: Table name to migrate
        dry_run: If True, show plan without executing
        confirm_data_loss: Required confirmation flag
        backup_retention_days: Backup retention period
        connection_string: Database connection string
    """
    if not connection_string:
        click.echo(
            "Error: Connection string required. "
            "Provide via --connection-string or agv_CONNECTION_STRING env var.",
            err=True,
        )
        sys.exit(1)

    # Initialize connection manager
    conn_manager = PostgresConnectionManager(connection_string=connection_string)
    await conn_manager.initialize()

    try:
        # Get current schema info
        tracker = SchemaVersionTracker(conn_manager)
        await tracker.ensure_meta_table()

        # Check current dimension
        conn = await conn_manager.acquire_for_transaction()
        try:
            from asyncpg.utils import _quote_ident as escape_identifier

            safe_table = escape_identifier(table)

            # Get current dimension
            current_dim = await conn.fetchval(
                """
                SELECT atttypmod - 4
                FROM pg_attribute a
                JOIN pg_class c ON a.attrelid = c.oid
                WHERE c.relname = $1 AND a.attname = 'embedding'
                """,
                table,
            )

            if current_dim is None:
                click.echo(
                    f"Error: Table {table} not found or has no embedding column",
                    err=True,
                )
                sys.exit(1)

            # Get row count
            row_count = await conn.fetchval(f"SELECT COUNT(*) FROM {safe_table}")
        finally:
            await conn_manager.release_transaction_connection(conn)

        if dry_run:
            # Show migration plan
            click.echo("=" * 70)
            click.echo("SCHEMA MIGRATION PLAN (DRY-RUN)")
            click.echo("=" * 70)
            click.echo(f"Project: {project}")
            click.echo(f"Table: {table}")
            click.echo(f"Current Dimension: {current_dim}")
            click.echo(f"New Dimension: {new_dimension}")
            click.echo(f"Rows Affected: {row_count:,}")
            click.echo("\nBackup Configuration:")
            click.echo(f"  - Retention: {backup_retention_days} days")
            click.echo(
                f"  - Table: _agv_migration_backup_{table}_<timestamp>"
            )
            click.echo("\nMigration Steps:")
            click.echo("  1. Create backup table (all columns except embedding)")
            click.echo(f"  2. Verify backup has {row_count:,} rows")
            click.echo("  3. Drop embedding column and index")
            click.echo(f"  4. Add new embedding column with dimension {new_dimension}")
            click.echo("  5. Mark all chunks as needs_reindex=True")
            click.echo("  6. Recreate index (empty)")
            click.echo("  7. Increment schema version")
            click.echo("\nWARNING: All {row_count:,} embeddings will be deleted!")
            click.echo("You must re-index all content after migration.")
            click.echo("\n" + "=" * 70)
            click.echo("To execute migration, add --confirm-data-loss flag")
            click.echo("=" * 70)
            return

        # Require confirmation for actual migration
        if not confirm_data_loss:
            click.echo(
                "Error: Migration requires --confirm-data-loss flag.\n"
                "This operation will DELETE all embeddings and require full re-indexing.\n"
                "Run with --dry-run first to preview changes.",
                err=True,
            )
            sys.exit(1)

        # Confirm dimension change
        if current_dim == new_dimension:
            click.echo(
                f"Error: Current dimension ({current_dim}) matches new dimension ({new_dimension}).\n"
                "No migration needed.",
                err=True,
            )
            sys.exit(1)

        # Execute migration
        click.echo("=" * 70)
        click.echo("SCHEMA MIGRATION")
        click.echo("=" * 70)
        click.echo(f"Project: {project}")
        click.echo(f"Table: {table}")
        click.echo(f"Current Dimension: {current_dim} → New Dimension: {new_dimension}")
        click.echo(f"Rows: {row_count:,}")
        click.echo("\nStarting migration...")

        migrator = SchemaMigrator(conn_manager, tracker)

        result = await migrator.migrate_dimension(
            table_name=table,
            column_name="embedding",
            new_dimension=new_dimension,
            backup_retention_days=backup_retention_days,
        )

        click.echo("\n" + "=" * 70)
        click.echo("MIGRATION COMPLETE")
        click.echo("=" * 70)
        click.echo(f"Backup Table: {result.backup_table_name}")
        click.echo(f"Backup Verified: ✓ ({result.rows_affected:,} rows)")
        click.echo(f"Dimension: {result.old_dimension} → {result.new_dimension}")
        click.echo(f"Duration: {result.duration_seconds:.2f} seconds")
        click.echo("\n" + "!" * 70)
        click.echo("IMPORTANT: Re-index all content to generate new embeddings")
        click.echo("!" * 70)

    except Exception as e:
        click.echo(f"\nError during migration: {e}", err=True)
        logger.exception("Schema migration failed")
        sys.exit(1)

    finally:
        await conn_manager.close()


async def _run_restore(
    project: str,
    backup_timestamp: str,
    table: str,
    connection_string: Optional[str],
):
    """Execute schema restore from backup.

    Args:
        project: Project ID
        backup_timestamp: Backup timestamp
        table: Table name to restore
        connection_string: Database connection string
    """
    if not connection_string:
        click.echo(
            "Error: Connection string required. "
            "Provide via --connection-string or agv_CONNECTION_STRING env var.",
            err=True,
        )
        sys.exit(1)

    # Initialize connection manager
    conn_manager = PostgresConnectionManager(connection_string=connection_string)
    await conn_manager.initialize()

    try:
        tracker = SchemaVersionTracker(conn_manager)
        migrator = SchemaMigrator(conn_manager, tracker)

        # Construct backup table name
        backup_table = f"_agv_migration_backup_{table}_{backup_timestamp}"

        # Verify backup exists
        conn = await conn_manager.acquire_for_transaction()
        try:
            from asyncpg.utils import _quote_ident as escape_identifier

            backup_exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = $1
                )
                """,
                backup_table,
            )

            if not backup_exists:
                click.echo(
                    f"Error: Backup table {backup_table} not found.\n"
                    "Available backups can be listed with: "
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_name LIKE '_agv_migration_backup_%';",
                    err=True,
                )
                sys.exit(1)

            safe_backup_table = escape_identifier(backup_table)
            backup_row_count = await conn.fetchval(
                f"SELECT COUNT(*) FROM {safe_backup_table}"
            )
        finally:
            await conn_manager.release_transaction_connection(conn)

        click.echo("=" * 70)
        click.echo("SCHEMA RESTORE")
        click.echo("=" * 70)
        click.echo(f"Project: {project}")
        click.echo(f"Target Table: {table}")
        click.echo(f"Backup Table: {backup_table}")
        click.echo(f"Backup Rows: {backup_row_count:,}")
        click.echo("\nWARNING: This will overwrite the current table!")
        click.echo("Are you sure you want to proceed? [y/N]: ", nl=False)

        confirmation = input()
        if confirmation.lower() != "y":
            click.echo("Restore cancelled.")
            return

        click.echo("\nStarting restore...")

        import time

        start_time = time.monotonic()
        rows_restored = await migrator.restore_from_backup(
            table_name=table, backup_table_name=backup_table
        )
        duration = time.monotonic() - start_time

        click.echo("\n" + "=" * 70)
        click.echo("RESTORE COMPLETE")
        click.echo("=" * 70)
        click.echo(f"Restored Rows: {rows_restored:,}")
        click.echo(f"Duration: {duration:.2f} seconds")
        click.echo("=" * 70)

    except Exception as e:
        click.echo(f"\nError during restore: {e}", err=True)
        logger.exception("Schema restore failed")
        sys.exit(1)

    finally:
        await conn_manager.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    schema()
