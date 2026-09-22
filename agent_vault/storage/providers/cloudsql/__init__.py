"""Cloud SQL storage provider for agent_vault.

This package provides GCP Cloud SQL-backed implementations using the
Cloud SQL Python Connector with Application Default Credentials (ADC).

The Cloud SQL provider reuses existing PostgreSQL providers but uses a
GCP-aware connection manager that handles IAM authentication and token refresh
automatically via the Cloud SQL Connector library.

Available Components:
- CloudSQLConnectionManager: Connection manager with ADC and IAM auth
- CloudSQLError: Sanitized error handling with error IDs
- CloudSQLErrorCode: Error codes with actionable guidance

Authentication:
    Uses Application Default Credentials (ADC) which works for:
    - Local dev: gcloud auth application-default login
    - GKE/Cloud Run: Workload Identity (automatic)
    - CI/CD: GOOGLE_APPLICATION_CREDENTIALS env var

Usage:
    from agent_vault.storage.providers.cloudsql import (
        CloudSQLError,
        CloudSQLErrorCode,
    )

    try:
        # Cloud SQL operations
        ...
    except CloudSQLError as e:
        logger.error("Cloud SQL error %s: %s", e.error_id, e.message)

Requirements:
    - google-cloud-sql-connector[asyncpg]: pip install google-cloud-sql-connector[asyncpg]
    - google-auth: pip install google-auth
    - pgvector extension in Cloud SQL PostgreSQL: CREATE EXTENSION vector;

Configuration Example:
    storage:
      backends:
        gcp_cloudsql:
          type: cloudsql
          project: my-gcp-project
          region: us-central1
          instance: agent-vault-db
          database: agent-vault
          user: app-service@my-gcp-project.iam
          pool_size: 10
          max_overflow: 5
"""

from agent_vault.storage.providers.cloudsql.connection import (
    CloudSQLConnectionManager,
)
from agent_vault.storage.providers.cloudsql.errors import (
    CloudSQLError,
    CloudSQLErrorCode,
)

__all__ = [
    "CloudSQLConnectionManager",
    "CloudSQLError",
    "CloudSQLErrorCode",
]
