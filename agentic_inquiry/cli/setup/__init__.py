"""Setup wizard module for Agentic Inquiry.

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
    >>> from agentic_inquiry.cli.setup import LocalSetup
    >>> setup = LocalSetup(env_name="dev", is_dev=True)
    >>> setup.run()
"""

from agentic_inquiry.cli.setup.base import BaseSetup, run_async
from agentic_inquiry.cli.setup.gcp_base import GCPBaseSetup
from agentic_inquiry.cli.setup.local_setup import LocalSetup
from agentic_inquiry.cli.setup.postgres_setup import PostgresSetup
from agentic_inquiry.cli.setup.gcp_setup import GCPSetup
from agentic_inquiry.cli.setup.alloydb_setup import AlloyDBSetup
from agentic_inquiry.cli.setup.aws_setup import AWSSetup
from agentic_inquiry.cli.setup.azure_setup import AzureSetup
from agentic_inquiry.cli.setup.templates import (
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
