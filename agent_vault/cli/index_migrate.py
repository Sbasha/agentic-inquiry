"""CLI command for index migration.

Provides `agv index migrate` command for explicit index migration with
support for different index types (HNSW, ivfflat) and dry-run mode.

Usage:
    # Migrate to HNSW index
    agv index migrate --project my_project --index-type hnsw

    # Migrate to ivfflat with explicit lists parameter
    agv index migrate --project my_project --index-type ivfflat --lists 200

    # Dry-run to preview migration
    agv index migrate --project my_project --index-type hnsw --dry-run

    # Specify custom table
    agv index migrate --project my_project --index-type hnsw --table agv_v_chunks
"""

import asyncio
import logging
import sys
from typing import Optional

import click

from agent_vault.storage.providers.postgresql.connection import (
    PostgresConnectionManager,
)
from agent_vault.storage.providers.postgresql.index_config import (
    HNSWParams,
    IndexConfig,
    IndexType,
    IVFFlatParams,
)
from agent_vault.storage.providers.postgresql.maintenance import (
    PostgresMaintenanceService,
)

logger = logging.getLogger(__name__)


@click.group()
def index():
    """Index management commands."""
    pass


@index.command("migrate")
@click.option(
    "--project",
    required=True,
    help="Project ID to migrate index for",
)
@click.option(
    "--index-type",
    type=click.Choice(["hnsw", "ivfflat"], case_sensitive=False),
    required=True,
    help="Target index type (hnsw or ivfflat)",
)
@click.option(
    "--lists",
    type=int,
    default=None,
    help="Explicit lists parameter for ivfflat (optional, will calculate if not provided)",
)
@click.option(
    "--m",
    type=int,
    default=16,
    help="HNSW m parameter (connections per layer, default: 16)",
)
@click.option(
    "--ef-construction",
    type=int,
    default=64,
    help="HNSW ef_construction parameter (build-time search width, default: 64)",
)
@click.option(
    "--table",
    default="agv_v_chunks",
    help="Table name to rebuild index for (default: agv_v_chunks)",
)
@click.option(
    "--column",
    default="embedding",
    help="Column name containing vectors (default: embedding)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be changed without actually migrating",
)
@click.option(
    "--connection-string",
    envvar="agv_CONNECTION_STRING",
    help="PostgreSQL connection string (or set agv_CONNECTION_STRING env var)",
)
@click.option(
    "--similarity-metric",
    type=click.Choice(["cosine", "l2", "dot"], case_sensitive=False),
    default="cosine",
    show_default=True,
    help="Similarity metric the target database was configured with. Controls "
    "which pgvector op-class is written into the rebuilt index "
    "(vector_cosine_ops / vector_l2_ops / vector_ip_ops).",
)
def migrate(
    project: str,
    index_type: str,
    lists: Optional[int],
    m: int,
    ef_construction: int,
    table: str,
    column: str,
    dry_run: bool,
    connection_string: Optional[str],
    similarity_metric: str,
):
    """Migrate vector index to a different type.

    This command rebuilds the vector index using CREATE INDEX CONCURRENTLY,
    which allows the operation to proceed without blocking reads or writes.

    WARNING: Index migration requires a full table scan and may take significant
    time on large datasets (e.g., 1M vectors may take 30-60 minutes).

    Examples:

        # Migrate to HNSW with defaults
        agv index migrate --project my_project --index-type hnsw

        # Migrate to ivfflat with custom lists
        agv index migrate --project my_project --index-type ivfflat --lists 200

        # Preview migration without executing
        agv index migrate --project my_project --index-type hnsw --dry-run
    """
    asyncio.run(
        _run_migrate(
            project=project,
            index_type=index_type,
            lists=lists,
            m=m,
            ef_construction=ef_construction,
            table=table,
            column=column,
            dry_run=dry_run,
            connection_string=connection_string,
            similarity_metric=similarity_metric.lower(),
        )
    )


async def _run_migrate(
    project: str,
    index_type: str,
    lists: Optional[int],
    m: int,
    ef_construction: int,
    table: str,
    column: str,
    dry_run: bool,
    connection_string: Optional[str],
    similarity_metric: str = "cosine",
):
    """Execute index migration.

    Args:
        project: Project ID
        index_type: Target index type ("hnsw" or "ivfflat")
        lists: Explicit ivfflat lists parameter
        m: HNSW m parameter
        ef_construction: HNSW ef_construction parameter
        table: Table name
        column: Column name
        dry_run: If True, show plan without executing
        connection_string: Database connection string
    """
    if not connection_string:
        click.echo(
            "Error: Connection string required. "
            "Provide via --connection-string or agv_CONNECTION_STRING env var.",
            err=True,
        )
        sys.exit(1)

    # Build index configuration
    idx_type = IndexType.HNSW if index_type.lower() == "hnsw" else IndexType.IVFFLAT

    if idx_type == IndexType.HNSW:
        index_config = IndexConfig(
            index_type=idx_type,
            hnsw_params=HNSWParams(m=m, ef_construction=ef_construction),
        )
    else:
        ivfflat_params = IVFFlatParams(lists=lists) if lists else None
        index_config = IndexConfig(index_type=idx_type, ivfflat_params=ivfflat_params)

    # Initialize connection manager with the configured similarity metric so
    # rebuild DDL emits the matching pgvector op-class.
    conn_manager = PostgresConnectionManager(
        connection_string=connection_string,
        similarity_metric=similarity_metric,
    )
    await conn_manager.initialize()

    try:
        maintenance_service = PostgresMaintenanceService(conn_manager)

        if dry_run:
            # Dry-run: show migration plan
            click.echo("=" * 70)
            click.echo("INDEX MIGRATION PLAN (DRY-RUN)")
            click.echo("=" * 70)
            click.echo(f"Project: {project}")
            click.echo(f"Table: {table}")
            click.echo(f"Column: {column}")
            click.echo(f"Target Index Type: {index_type.upper()}")

            if idx_type == IndexType.HNSW:
                click.echo("HNSW Parameters:")
                click.echo(f"  - m: {m}")
                click.echo(f"  - ef_construction: {ef_construction}")
            elif idx_type == IndexType.IVFFLAT:
                if lists:
                    click.echo("IVFFlat Parameters:")
                    click.echo(f"  - lists: {lists} (explicit)")
                else:
                    click.echo("IVFFlat Parameters:")
                    click.echo("  - lists: (will be calculated from row count)")

            # Get current row count
            # Use internal pool directly for dry-run query since we need direct connection
            if not conn_manager._pool:
                raise RuntimeError("Connection pool not initialized")

            async with conn_manager._pool.acquire() as conn:
                from asyncpg.utils import _quote_ident as escape_identifier

                safe_table = escape_identifier(table)
                row_count = await conn.fetchval(f"SELECT COUNT(*) FROM {safe_table}")

            click.echo(f"\nCurrent row count: {row_count:,}")

            if idx_type == IndexType.IVFFLAT and not lists:
                import math

                calculated_lists = max(
                    1, min(int(math.floor(math.sqrt(row_count))), 10000)
                )
                click.echo(f"Calculated lists parameter: {calculated_lists}")

            click.echo("\nEstimated duration:")
            if row_count < 100_000:
                click.echo("  < 5 minutes")
            elif row_count < 500_000:
                click.echo("  5-15 minutes")
            elif row_count < 1_000_000:
                click.echo("  15-30 minutes")
            else:
                click.echo("  30-60 minutes or more")

            click.echo("\n" + "=" * 70)
            click.echo("To execute migration, run without --dry-run flag")
            click.echo("=" * 70)
            return

        # Actual migration
        click.echo("=" * 70)
        click.echo("INDEX MIGRATION")
        click.echo("=" * 70)
        click.echo(f"Project: {project}")
        click.echo(f"Table: {table}")
        click.echo(f"Column: {column}")
        click.echo(f"Target Index Type: {index_type.upper()}")
        click.echo("\nStarting migration...")
        click.echo(
            "Note: This operation uses CONCURRENTLY to avoid blocking reads/writes."
        )

        result = await maintenance_service.rebuild_index(
            table_name=table,
            column_name=column,
            index_config=index_config,
        )

        click.echo("\n" + "=" * 70)
        click.echo("MIGRATION COMPLETE")
        click.echo("=" * 70)
        click.echo(f"Index Name: {result.index_name}")
        click.echo(f"Index Type: {result.index_type}")
        click.echo(f"Rows Indexed: {result.rows_indexed:,}")
        click.echo(f"Duration: {result.duration_seconds:.2f} seconds")
        click.echo(f"Index Size: {result.index_size_bytes / (1024**2):.2f} MB")
        click.echo("=" * 70)

    except Exception as e:
        click.echo(f"\nError during migration: {e}", err=True)
        logger.exception("Index migration failed")
        sys.exit(1)

    finally:
        await conn_manager.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    index()
