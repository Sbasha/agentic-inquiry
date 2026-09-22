"""Interactive setup wizard for Agentic Inquiry.

This module provides the main entry point for the setup wizard, routing to
appropriate backend-specific handlers based on command-line arguments.

Usage:
    ai setup                  # Interactive mode - prompts for backend type
    ai setup local [name]     # LanceDB (development)
    ai setup postgres [name]  # PostgreSQL (direct connection)
    ai setup gcp [name]       # CloudSQL (GCP managed)
    ai setup --dev            # Create test environment

Environment Naming:
    - Default: 'ai' (production)
    - With --dev: 'ai-test' or 'ai-test-<name>'
    - Test environments never auto-start proxy
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from agentic_inquiry.cli.setup.base import (
    prompt_choice,
    print_error,
    print_info,
)
from agentic_inquiry.cli.setup.local_setup import LocalSetup
from agentic_inquiry.cli.setup.postgres_setup import PostgresSetup
from agentic_inquiry.cli.setup.gcp_setup import GCPSetup
from agentic_inquiry.cli.setup.alloydb_setup import AlloyDBSetup
from agentic_inquiry.cli.setup.aws_setup import AWSSetup


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for setup command.

    Returns:
        Configured ArgumentParser
    """
    parser = argparse.ArgumentParser(
        description="Configure Agentic Inquiry storage backend",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ai setup                    Interactive mode
  ai setup local              LanceDB (development)
  ai setup alloydb            AlloyDB (GCP, server-side embeddings)
  ai setup gcp                CloudSQL (GCP, standard PostgreSQL)
  ai setup postgres           PostgreSQL (direct connection)
  ai setup aws                RDS (AWS managed)
""",
    )

    parser.add_argument(
        "backend",
        nargs="?",
        choices=["local", "postgres", "gcp", "alloydb", "aws", "azure"],
        help="Backend type: local (LanceDB), postgres (PostgreSQL), gcp (CloudSQL), alloydb (AlloyDB), aws (RDS), azure (PostgreSQL)",
    )

    parser.add_argument(
        "name",
        nargs="?",
        help="Environment name (default: 'ai' or 'ai-test' with --dev)",
    )

    parser.add_argument(
        "--dev",
        action="store_true",
        help="Create a test/development environment (no auto-start proxy)",
    )

    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Workspace root path (default: current directory)",
    )

    # PostgreSQL-specific options
    parser.add_argument(
        "--connection-string",
        help="PostgreSQL connection string (for postgres backend)",
    )

    # GCP/AlloyDB-specific options
    parser.add_argument(
        "--project",
        help="GCP project ID (for gcp/alloydb backend)",
    )

    parser.add_argument(
        "--region",
        help="Cloud region — GCP region (for gcp/alloydb) or AWS region (for aws backend)",
    )

    parser.add_argument(
        "--cluster",
        help="AlloyDB cluster name (for alloydb backend)",
    )

    parser.add_argument(
        "--instance",
        help="Cloud instance name — Cloud SQL instance (for gcp) or AlloyDB instance (for alloydb) or RDS identifier (for aws)",
    )

    parser.add_argument(
        "--database",
        help="Database name (for postgres/gcp/aws backend)",
    )

    parser.add_argument(
        "--user",
        help="Database user (for gcp/aws backend)",
    )

    parser.add_argument(
        "--table-prefix",
        default="agv_",
        help="Table prefix for schema isolation (default: agv_)",
    )

    # AWS-specific options
    parser.add_argument(
        "--host",
        help="RDS endpoint hostname (for aws backend; auto-discovered if omitted)",
    )

    parser.add_argument(
        "--password",
        help="Database password (for aws backend; omit when using --use-iam-auth)",
    )

    parser.add_argument(
        "--use-iam-auth",
        action="store_true",
        default=False,
        help="Use AWS IAM token authentication for RDS (for aws backend)",
    )

    return parser


def run_interactive_setup(
    is_dev: bool = False,
    workspace: Optional[Path] = None,
) -> bool:
    """Run interactive setup when no backend type is specified.

    Args:
        is_dev: Whether to create a test environment
        workspace: Workspace root path

    Returns:
        True if setup completed successfully
    """
    print("========================================")
    print("  Agentic Inquiry Environment Setup")
    print("========================================")

    print_info("Select the storage backend for your environment.")
    print_info("")
    print_info("LanceDB (Local) - Best for development")
    print_info("  - No external dependencies")
    print_info("  - Fast, embedded vector database")
    print_info("  - SQLite for metadata")
    print_info("")
    print_info("PostgreSQL (Direct) - For self-managed PostgreSQL")
    print_info("  - Direct connection via connection string")
    print_info("  - Requires pgvector extension")
    print_info("  - Good for on-premise or cloud PostgreSQL")
    print_info("")
    print_info("AlloyDB (GCP) - [RECOMMENDED for GCP]")
    print_info("  - Native server-side embeddings via Vertex AI")
    print_info("  - Highest performance vector search")
    print_info("  - Automatic AlloyDB Auth Proxy management")
    print_info("")
    print_info("CloudSQL (GCP) - For standard GCP PostgreSQL")
    print_info("  - IAM authentication via ADC")
    print_info("  - Automatic Cloud SQL Proxy management")
    print_info("")
    print_info("RDS (AWS) - For AWS-managed PostgreSQL")
    print_info("  - Direct SSL connection to RDS")
    print_info("  - Password or IAM token authentication")
    print_info("  - Best for AWS production environments")
    print_info("")
    print_info("Azure (Managed) - For Azure Database for PostgreSQL")
    print_info("  - Direct connection to Azure PostgreSQL")
    print_info("  - Native server-side embeddings via Azure OpenAI")
    print_info("  - Best for Azure production environments")

    choice = prompt_choice(
        "\nSelect storage backend:",
        ["LanceDB (Local)", "AlloyDB (GCP)", "CloudSQL (GCP)", "PostgreSQL (Direct)", "RDS (AWS)", "Azure (Managed)"],
    )

    if choice.startswith("LanceDB"):
        setup = LocalSetup(is_dev=is_dev, workspace=workspace)
    elif choice.startswith("AlloyDB"):
        setup = AlloyDBSetup(is_dev=is_dev, workspace=workspace)
    elif choice.startswith("PostgreSQL"):
        setup = PostgresSetup(is_dev=is_dev, workspace=workspace)
    elif choice.startswith("RDS"):
        setup = AWSSetup(is_dev=is_dev, workspace=workspace)
    elif choice.startswith("Azure"):
        from agentic_inquiry.cli.setup.azure_setup import AzureSetup
        setup = AzureSetup(is_dev=is_dev, workspace=workspace)
    else:
        setup = GCPSetup(is_dev=is_dev, workspace=workspace)

    return setup.run()


def run_setup(args: Optional[list[str]] = None) -> bool:
    """Run the setup wizard with the given arguments.

    Args:
        args: Command-line arguments (defaults to sys.argv[1:])

    Returns:
        True if setup completed successfully
    """
    parser = create_parser()
    parsed = parser.parse_args(args)

    workspace = parsed.workspace or Path.cwd()
    is_dev = parsed.dev

    # If no backend specified, run interactive mode
    if not parsed.backend:
        return run_interactive_setup(is_dev=is_dev, workspace=workspace)

    # Route to appropriate handler based on backend type
    if parsed.backend == "local":
        setup = LocalSetup(
            env_name=parsed.name,
            is_dev=is_dev,
            workspace=workspace,
        )
        return setup.run()

    elif parsed.backend == "alloydb":
        setup = AlloyDBSetup(
            env_name=parsed.name,
            is_dev=is_dev,
            workspace=workspace,
            project=parsed.project,
            region=parsed.region,
            cluster=parsed.cluster,
            instance=parsed.instance,
            database=parsed.database,
            user=parsed.user,
            table_prefix=parsed.table_prefix,
        )
        return setup.run()

    elif parsed.backend == "postgres":
        setup = PostgresSetup(
            env_name=parsed.name,
            is_dev=is_dev,
            workspace=workspace,
            connection_string=parsed.connection_string,
            table_prefix=parsed.table_prefix,
        )
        return setup.run()

    elif parsed.backend == "gcp":
        setup = GCPSetup(
            env_name=parsed.name,
            is_dev=is_dev,
            workspace=workspace,
            project=parsed.project,
            region=parsed.region,
            instance=parsed.instance,
            database=parsed.database,
            user=parsed.user,
            table_prefix=parsed.table_prefix,
        )
        return setup.run()

    elif parsed.backend == "aws":
        setup = AWSSetup(
            env_name=parsed.name,
            is_dev=is_dev,
            workspace=workspace,
            region=parsed.region,
            instance=parsed.instance,
            host=getattr(parsed, "host", None),
            database=parsed.database,
            user=parsed.user,
            password=getattr(parsed, "password", None),
            use_iam_auth=getattr(parsed, "use_iam_auth", False),
            table_prefix=parsed.table_prefix,
        )
        return setup.run()

    elif parsed.backend == "azure":
        from agentic_inquiry.cli.setup.azure_setup import AzureSetup
        setup = AzureSetup(
            env_name=parsed.name,
            is_dev=is_dev,
            workspace=workspace,
            host=getattr(parsed, "host", None),
            database=parsed.database,
            user=parsed.user,
            password=getattr(parsed, "password", None),
            table_prefix=parsed.table_prefix,
        )
        return setup.run()

    else:
        print_error(f"Unknown backend: {parsed.backend}")
        return False


# Legacy entry point for backward compatibility
def run_setup_legacy() -> None:
    """Legacy entry point - runs interactive setup.

    This function maintains backward compatibility with the old setup wizard
    that only supported interactive mode.
    """
    success = run_setup()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    success = run_setup()
    sys.exit(0 if success else 1)
