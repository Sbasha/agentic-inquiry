"""Maintenance operations CLI for Agent-Vault.

This module provides CLI commands for database maintenance operations:
- `agv maintenance run` - Run vacuum and/or reindex operations (FR-6)

Usage:
    agv maintenance run --operation vacuum
    agv maintenance run --operation reindex
    agv maintenance run --operation all

Design decisions:
    - Progress reporting for long-running operations
    - Statistics display for observability
    - Support for operation selection (vacuum, reindex, all)
    - Async execution for large databases

Example:
    $ agv maintenance run --operation vacuum
    Running VACUUM ANALYZE on tables...
    ✓ Completed in 45.2s
    Statistics:
      - Dead tuples removed: 1,234
      - Pages reclaimed: 567
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Literal, Optional, cast

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from agent_vault.config import StorageConfig
from agent_vault.storage.config import BackendConfig
from agent_vault.storage.providers.postgresql.connection import (
    PostgresConnectionManager,
)
from agent_vault.storage.providers.postgresql.maintenance import (
    PostgresMaintenanceService,
)

logger = logging.getLogger(__name__)

console = Console()


@click.group()
def maintenance():
    """Database maintenance operations."""
    pass


def _load_config(config_path: Optional[Path] = None) -> StorageConfig:
    """Load storage configuration from file."""
    if config_path is None:
        config_path = Path.cwd() / "storage_config.yaml"

    if not config_path.exists():
        console.print(
            f"[red]Error:[/red] Configuration file not found: {config_path}",
        )
        console.print(
            "\nCreate a storage_config.yaml file with your backend configuration.",
        )
        sys.exit(1)

    try:
        import yaml

        with open(config_path) as f:
            data = yaml.safe_load(f)

        return StorageConfig(**data)
    except Exception as e:
        console.print(f"[red]Error loading configuration:[/red] {e}")
        sys.exit(1)


def _get_postgresql_backend(config: StorageConfig) -> BackendConfig:
    """Get PostgreSQL backend from configuration."""
    # Look for postgresql backend
    if config.backends:
        for backend in config.backends.values():
            if isinstance(backend, BackendConfig) and backend.type in (
                "postgresql",
                "cloudsql",
            ):
                return backend
            # Handle dict case if Pydantic model dump
            if isinstance(backend, dict) and backend.get("type") in (
                "postgresql",
                "cloudsql",
            ):
                return BackendConfig(**backend)

    console.print(
        "[red]Error:[/red] No PostgreSQL backend found in configuration",
    )
    console.print(
        "\nMaintenance operations require a PostgreSQL backend.",
    )
    sys.exit(1)


async def _run_maintenance_async(
    backend: BackendConfig,
    operation: Literal["vacuum", "reindex", "all"],
    project_id: Optional[str] = None,
) -> None:
    """Run maintenance operations asynchronously.

    Args:
        backend: PostgreSQL backend configuration
        operation: Maintenance operation to run
        project_id: Optional project ID for table naming
    """
    if not backend.connection_string:
        raise ValueError("Backend configuration must include connection_string")

    # Create connection manager via from_backend_config so the configured
    # similarity_metric flows into rebuild DDL on a non-cosine deployment.
    connection_manager = PostgresConnectionManager.from_backend_config(backend)
    await connection_manager.initialize()

    try:
        # Create maintenance service
        service = PostgresMaintenanceService(connection_manager)

        # Construct table name with optional project prefix
        # Use standard table name - project isolation is handled by table prefix in config
        default_table = "agv_v_chunks"
        results = []

        # Run maintenance with progress indicator
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            if operation == "vacuum":
                task = progress.add_task(
                    "Running VACUUM ANALYZE on tables...", total=None
                )
                result = await service.run_maintenance(
                    operation="vacuum", table_name=default_table
                )
                results.append(result)
                progress.update(task, completed=True)

                console.print(
                    f"\n[green]✓[/green] Completed in {result.duration_seconds:.1f}s\n"
                )

            elif operation == "reindex":
                task = progress.add_task("Rebuilding indexes...", total=None)
                result = await service.run_maintenance(
                    operation="reindex", table_name=default_table
                )
                results.append(result)
                progress.update(task, completed=True)

                console.print(
                    f"\n[green]✓[/green] Completed in {result.duration_seconds:.1f}s\n"
                )

            else:  # operation == "all"
                task = progress.add_task(
                    "Running all maintenance operations...", total=None
                )
                start_time = time.monotonic()
                # Run both vacuum and reindex
                vacuum_result = await service.run_maintenance(
                    operation="vacuum", table_name=default_table
                )
                results.append(vacuum_result)
                reindex_result = await service.run_maintenance(
                    operation="reindex", table_name=default_table
                )
                results.append(reindex_result)
                total_duration = time.monotonic() - start_time
                progress.update(task, completed=True)

                console.print(
                    f"\n[green]✓[/green] Completed in {total_duration:.1f}s\n"
                )

        # Display statistics
        _display_statistics(results)

    finally:
        await connection_manager.close()


def _display_statistics(results: list) -> None:
    """Display maintenance operation statistics."""
    from agent_vault.storage.providers.postgresql.maintenance import MaintenanceResult

    table = Table(title="Maintenance Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    # Extract statistics from results
    total_duration = 0.0
    for result in results:
        if isinstance(result, MaintenanceResult):
            if result.operation == "vacuum":
                table.add_row("VACUUM executed", "✓")
            elif result.operation == "reindex":
                table.add_row("Index rebuild", "✓")
            total_duration += result.duration_seconds

            # Add operation-specific stats
            if result.statistics:
                for key, value in result.statistics.items():
                    table.add_row(f"  {key}", str(value))

    # Display operation count
    table.add_row("Operations completed", str(len(results)))

    # Display total duration
    table.add_row("Total duration", f"{total_duration:.1f}s")

    console.print(table)
    console.print()


@maintenance.command("run")
@click.option(
    "--operation",
    "-o",
    default="all",
    type=click.Choice(["vacuum", "reindex", "all"]),
    help="Maintenance operation to run: vacuum, reindex, or all",
)
@click.option(
    "--project",
    "-p",
    default=None,
    help="Project ID for table prefix (overrides config project_id if set)",
)
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    type=click.Path(exists=False, path_type=Path),
    help="Path to storage configuration file (default: ./storage_config.yaml)",
)
def run(
    operation: str,
    project: Optional[str],
    config_path: Optional[Path],
) -> None:
    """Run database maintenance operations.

    Operations:
        vacuum  - Run VACUUM ANALYZE to reclaim space and update statistics (AC-10)
        reindex - Rebuild indexes with CONCURRENTLY (AC-11)
        all     - Run all maintenance operations

    Examples:

        # Run vacuum only
        agv maintenance run --operation vacuum

        # Rebuild indexes
        agv maintenance run --operation reindex

        # Run all maintenance operations
        agv maintenance run --operation all

        # Use custom config file
        agv maintenance run --operation vacuum --config /path/to/config.yaml

        # Run maintenance for a specific project
        agv maintenance run --operation vacuum --project my_project
    """
    # Load configuration
    console.print(
        f"Loading configuration from {config_path or 'storage_config.yaml'}..."
    )
    config = _load_config(config_path)
    backend = _get_postgresql_backend(config)

    # Determine effective project ID (CLI override takes precedence)
    effective_project = project if project else getattr(config, "project_id", None)

    # Display operation info
    console.print(f"\n[bold]Maintenance Operation:[/bold] {operation}")
    console.print(f"[bold]Backend:[/bold] {backend.type}")
    if effective_project:
        console.print(f"[bold]Project:[/bold] {effective_project}")
    console.print()

    # Run maintenance
    try:
        # Cast operation to Literal for type checking
        op_literal = cast(Literal["vacuum", "reindex", "all"], operation)
        asyncio.run(_run_maintenance_async(backend, op_literal, effective_project))
        console.print("[green]Maintenance completed successfully.[/green]")
    except Exception as e:
        console.print(f"\n[red]Error during maintenance:[/red] {e}")
        logger.exception("Maintenance operation failed")
        sys.exit(1)


if __name__ == "__main__":
    maintenance()
