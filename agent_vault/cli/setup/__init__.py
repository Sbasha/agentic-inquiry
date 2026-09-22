"""Setup wizard module for Agent-Vault.

This module provides modular setup handlers for different storage backends:
- LocalSetup: LanceDB (development)
- PostgresSetup: PostgreSQL (direct connection)
- GCPSetup: CloudSQL (GCP managed)
- AlloyDBSetup: AlloyDB (GCP managed, server-side embeddings)
- AWSSetup: RDS (AWS managed)
- AzureSetup: Azure Database for PostgreSQL (managed)

Inheritance hierarchy:
    BaseSetup (base.py) - env directory, config writing, registry
        ├── LocalSetup (local_setup.py) - LanceDB
        ├── PostgresSetup (postgres_setup.py) - direct PostgreSQL
        ├── AWSSetup (aws_setup.py) - AWS RDS
        ├── AzureSetup (azure_setup.py) - Azure PostgreSQL
        └── GCPBaseSetup (gcp_base.py) - shared GCP auth/project/user
                ├── GCPSetup (gcp_setup.py) - Cloud SQL
                └── AlloyDBSetup (alloydb_setup.py) - AlloyDB

Example:
    >>> from agent_vault.cli.setup import LocalSetup
    >>> setup = LocalSetup(env_name="dev", is_dev=True)
    >>> setup.run()
"""

from agent_vault.cli.setup.base import BaseSetup, run_async
from agent_vault.cli.setup.gcp_base import GCPBaseSetup
from agent_vault.cli.setup.local_setup import LocalSetup
from agent_vault.cli.setup.postgres_setup import PostgresSetup
from agent_vault.cli.setup.gcp_setup import GCPSetup
from agent_vault.cli.setup.alloydb_setup import AlloyDBSetup
from agent_vault.cli.setup.aws_setup import AWSSetup
from agent_vault.cli.setup.azure_setup import AzureSetup
from agent_vault.cli.setup.templates import (
    LANCEDB_TEMPLATE,
    POSTGRES_TEMPLATE,
    CLOUDSQL_TEMPLATE,
    ALLOYDB_TEMPLATE,
    RDS_TEMPLATE,
    AZURE_TEMPLATE,
    render_template,
)

__all__ = [
    "BaseSetup",
    "GCPBaseSetup",
    "LocalSetup",
    "PostgresSetup",
    "GCPSetup",
    "AlloyDBSetup",
    "AWSSetup",
    "AzureSetup",
    "run_async",
    "LANCEDB_TEMPLATE",
    "POSTGRES_TEMPLATE",
    "CLOUDSQL_TEMPLATE",
    "ALLOYDB_TEMPLATE",
    "RDS_TEMPLATE",
    "AZURE_TEMPLATE",
    "render_template",
]
