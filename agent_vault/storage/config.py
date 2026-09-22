"""Configuration models for storage backends.

This module provides pydantic-based configuration for named storage backends
with validation for type-dependent fields.

Design principles:
    - Type-safe configuration with pydantic validation
    - Fail-fast validation at configuration time
    - Clear error messages for misconfiguration
    - Support for all backend types: lancedb, postgresql, sqlite, spanner, memory

Example:
    >>> config = BackendConfig(type="postgresql", connection_string="postgres://...")
    >>> config = BackendConfig(type="lancedb", database_path="./data/lancedb")
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from typing_extensions import Self

from agent_vault.storage.similarity import (
    DEFAULT_SIMILARITY_METRIC,
    SUPPORTED_METRICS,
    SimilarityMetric,
)


# Supported backend types
BackendType = Literal[
    "lancedb",
    "postgresql",
    "sqlite",
    "spanner",
    "cloudsql",
    "alloydb",
    "rds",
    "azure",
    "memory",
]

# Valid storage roles
StorageRole = Literal["vector", "graph", "events", "file_tracker"]


class BackendConfig(BaseModel):
    """Configuration for a named storage backend.

    This model validates that required fields are present based on backend type:
    - lancedb: requires database_path
    - sqlite: requires database_path
    - postgresql: requires connection_string
    - spanner: requires project_id, instance_id, database_id
    - cloudsql: requires project, region, instance, database, user
    - rds: requires region, instance, host, database, user
    - memory: no additional requirements

    Pool settings are only relevant for backends that support connection pooling
    (postgresql, spanner, cloudsql, rds).

    Attributes:
        type: Backend type identifier
        connection_string: PostgreSQL connection string (required for postgresql)
        database_path: Path to local database (required for lancedb, sqlite)
        pool_size: Base connection pool size (default: 10)
        max_overflow: Maximum pool overflow connections (default: 5)
        project_id: GCP project ID (required for spanner)
        instance_id: Spanner instance ID (required for spanner)
        database_id: Spanner database ID (required for spanner)
        project: GCP project ID (required for cloudsql)
        region: Cloud region — GCP region for cloudsql/alloydb, AWS region for rds
        instance: Cloud instance name — Cloud SQL instance for cloudsql, RDS instance ID for rds
        host: Hostname for direct connections (required for rds — the RDS endpoint)
        database: Database name (required for cloudsql/rds)
        user: Database user (required for cloudsql/rds)
        use_iam_auth: Use AWS IAM token authentication instead of password (rds only)
        table_prefix: Optional prefix for table names (for schema isolation)
        index_type: Vector index type ("hnsw", "ivfflat", "none"), default "hnsw"
        index_params: Optional index parameters (e.g., {"m": 16, "ef_construction": 64})
        expected_rows: Expected row count for ivfflat lists calculation
        fts_language: PostgreSQL full-text search language (default: "english")
        ssl_mode: SSL mode for direct connections ("disable", "allow", "prefer",
            "require", "verify-ca", "verify-full"). Required for direct Cloud SQL connections.
        ssl_ca_cert: Path to CA certificate file (required when ssl_mode="verify-full")

    Example:
        >>> # PostgreSQL backend
        >>> pg_config = BackendConfig(
        ...     type="postgresql",
        ...     connection_string="postgresql://user:pass@localhost/db",
        ...     pool_size=10,
        ... )
        >>>
        >>> # LanceDB backend
        >>> lance_config = BackendConfig(
        ...     type="lancedb",
        ...     database_path="./data/lancedb",
        ... )
        >>>
        >>> # Spanner backend
        >>> spanner_config = BackendConfig(
        ...     type="spanner",
        ...     project_id="my-project",
        ...     instance_id="my-instance",
        ...     database_id="my-database",
        ... )
        >>>
        >>> # AWS RDS backend
        >>> rds_config = BackendConfig(
        ...     type="rds",
        ...     region="us-east-1",
        ...     instance="my-rds-instance",
        ...     host="my-rds-instance.xxxxx.us-east-1.rds.amazonaws.com",
        ...     database="agent-vault",
        ...     user="agv_user",
        ...     password="secret",
        ... )
    """

    model_config = ConfigDict(
        frozen=False,  # Allow mutation for configuration updates
        extra="forbid",  # Reject unknown fields for strict validation
        validate_assignment=True,  # Validate on attribute assignment
    )

    # Backend type (required)
    type: BackendType

    # Connection settings (type-dependent)
    connection_string: Optional[str] = None
    database_path: Optional[str] = None

    # Pool settings (for pooled backends)
    pool_size: int = 10
    min_pool_size: int = 2
    max_overflow: int = 5

    # Per-statement command timeout (seconds) for asyncpg-based managers.
    # None lets each connection manager apply its own backend-appropriate
    # default (e.g. 60s for self-hosted postgresql, 900s for AlloyDB /
    # CloudSQL / RDS / Azure where bulk-embedding paths are slow).
    # Explicit values always override.
    command_timeout: Optional[float] = None

    # Spanner-specific settings
    project_id: Optional[str] = None
    instance_id: Optional[str] = None
    database_id: Optional[str] = None

    # Cloud SQL / AlloyDB-specific settings
    project: Optional[str] = None
    region: Optional[str] = None
    instance: Optional[str] = None
    database: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None  # Database password (if proxy requires it)
    cluster: Optional[str] = None  # AlloyDB cluster name
    port: int = 5432  # Proxy listen port (default: 5432 for AlloyDB, 5433 for CloudSQL)
    ssl: bool = True  # Whether to use SSL for proxy connections

    # RDS-specific settings
    host: Optional[str] = None  # Hostname for direct connections (e.g. RDS endpoint)
    use_iam_auth: bool = False  # Use AWS IAM token auth instead of password (rds only)

    # Schema isolation
    table_prefix: Optional[str] = None

    # Index configuration (FR-1)
    index_type: Literal["hnsw", "ivfflat", "none"] = "hnsw"
    index_params: Optional[dict] = None
    expected_rows: Optional[int] = None

    # Full-text search configuration (FR-5)
    fts_language: str = "english"

    # SSL/TLS configuration (SEC-1)
    ssl_mode: Optional[
        Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"]
    ] = None
    ssl_ca_cert: Optional[str] = None

    # Direct connection opt-in (SEC-1, FR-4)
    # Required when using connection_string without Cloud SQL connector
    allow_direct_connection: bool = False

    # Embedding strategy: "local" uses SentenceTransformer, "server_side" uses
    # database-native embedding (e.g. AlloyDB embedding() function via Vertex AI).
    # When server_side: embeddings are generated by the database, not locally.
    embedding_strategy: Literal["local", "server_side"] = "local"

    # Server-side embedding model name (only used when embedding_strategy=server_side)
    embedding_model: Optional[str] = None

    # Embedding dimensions (overrides default 384 when set)
    embedding_dim: Optional[int] = None

    # Similarity metric used for vector index creation and search.
    # Canonical names: "cosine", "l2", "dot". Backends translate these to
    # their own spellings (see agent_vault.storage.similarity).
    #
    # Honoured end-to-end on LanceDB and on the unified pgvector provider
    # (postgresql / cloudsql / alloydb / rds). Backends translate the metric
    # to the appropriate operator class for indexes and the matching distance
    # operator at query time.
    similarity_metric: SimilarityMetric = DEFAULT_SIMILARITY_METRIC

    @field_validator("pool_size")
    @classmethod
    def validate_pool_size(cls, v: int) -> int:
        """Validate pool_size is positive."""
        if v < 1:
            raise ValueError("pool_size must be at least 1")
        return v

    @field_validator("max_overflow")
    @classmethod
    def validate_max_overflow(cls, v: int) -> int:
        """Validate max_overflow is non-negative."""
        if v < 0:
            raise ValueError("max_overflow must be non-negative")
        return v

    @model_validator(mode="after")
    def validate_type_requirements(self) -> "BackendConfig":
        """Validate type-dependent field requirements.

        Raises:
            ValueError: If required fields for the backend type are missing
        """
        backend_type = self.type

        if backend_type == "postgresql":
            # PostgreSQL can use either connection_string OR Cloud SQL params
            has_connection_string = bool(self.connection_string)
            has_cloud_sql_params = bool(self.project and self.region and self.instance)
            if not has_connection_string and not has_cloud_sql_params:
                raise ValueError(
                    "postgresql backend requires either connection_string or "
                    "Cloud SQL params (project, region, instance, database, user)"
                )

        elif backend_type in ("lancedb", "sqlite"):
            if not self.database_path:
                raise ValueError(
                    f"database_path is required for {backend_type} backend"
                )

        elif backend_type == "spanner":
            missing = []
            if not self.project_id:
                missing.append("project_id")
            if not self.instance_id:
                missing.append("instance_id")
            if not self.database_id:
                missing.append("database_id")
            if missing:
                raise ValueError(f"spanner backend requires: {', '.join(missing)}")

        # memory type has no requirements

        return self

    @model_validator(mode="after")
    def validate_similarity_metric(self) -> Self:
        """Validate similarity_metric is one of the canonical names."""
        if self.similarity_metric not in SUPPORTED_METRICS:
            raise ValueError(
                f"Unsupported similarity_metric '{self.similarity_metric}'. "
                f"Supported: {sorted(SUPPORTED_METRICS)}"
            )
        return self

    @model_validator(mode="after")
    def validate_cloudsql_config(self) -> Self:
        """Validate Cloud SQL-specific configuration requirements.

        Raises:
            ValueError: If required Cloud SQL fields are missing or invalid
        """
        if self.type != "cloudsql":
            return self

        required = ["project", "region", "instance", "database", "user"]
        missing = [f for f in required if not getattr(self, f, None)]

        if missing:
            raise ValueError(
                f"Cloud SQL backend requires: {', '.join(missing)}. "
                f"Example: BackendConfig(type='cloudsql', project='my-proj', "
                f"region='us-central1', instance='my-instance', database='agv', user='agv-user')"
            )

        # Validate format constraints
        if self.project and not re.match(
            r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$", self.project
        ):
            raise ValueError(f"Invalid GCP project ID format: {self.project}")

        # Validate instance name (alphanumeric + hyphens, max 64 chars)
        if self.instance and not re.match(
            r"^[a-z][a-z0-9-]{0,62}[a-z0-9]$", self.instance
        ):
            raise ValueError(f"Invalid Cloud SQL instance name: {self.instance}")

        # Validate database name (alphanumeric + underscores, max 63 chars)
        if self.database and not re.match(r"^[a-z_][a-z0-9_]{0,62}$", self.database):
            raise ValueError(f"Invalid database name: {self.database}")

        # Validate user (IAM format or standard user, max 63 chars)
        if self.user and (len(self.user) > 63 or not self.user):
            raise ValueError("Invalid user: must be 1-63 characters")

        # Validate region format
        if self.region and not re.match(r"^[a-z]+-[a-z]+\d+(-[a-z])?$", self.region):
            raise ValueError(f"Invalid GCP region format: {self.region}")

        return self

    @model_validator(mode="after")
    def validate_alloydb_config(self) -> Self:
        """Validate AlloyDB-specific configuration requirements.

        When type='alloydb', auto-sets embedding_strategy to 'server_side'
        and embedding_model to 'text-embedding-005' if not already set.
        AlloyDB is treated as a PostgreSQL variant with server-side embeddings.

        Raises:
            ValueError: If required AlloyDB fields are missing or invalid
        """
        if self.type != "alloydb":
            return self

        required = ["project", "region", "cluster", "instance", "database", "user"]
        missing = [f for f in required if not getattr(self, f, None)]

        if missing:
            raise ValueError(
                f"AlloyDB backend requires: {', '.join(missing)}. "
                f"Example: BackendConfig(type='alloydb', project='my-proj', "
                f"region='us-central1', cluster='my-cluster', instance='primary', "
                f"database='agv', user='agv-user')"
            )

        # Auto-configure server-side embeddings for AlloyDB
        if self.embedding_strategy == "local":
            self.embedding_strategy = "server_side"
        if not self.embedding_model:
            self.embedding_model = "text-embedding-005"
        if not self.embedding_dim:
            self.embedding_dim = 768

        return self

    @model_validator(mode="after")
    def validate_rds_config(self) -> Self:
        """Validate AWS RDS-specific configuration requirements.

        When type='rds' and embedding_strategy='server_side', auto-configures
        sensible defaults for Amazon Bedrock embeddings via Aurora PostgreSQL:
        - embedding_model defaults to 'amazon.titan-embed-text-v2:0'
        - embedding_dim defaults to 1024 (Titan Embeddings v2 default)

        Server-side embeddings require Aurora PostgreSQL 15.3+ with the
        aws_ml extension and appropriate IAM permissions for Bedrock.

        Raises:
            ValueError: If required RDS fields are missing or invalid
        """
        if self.type != "rds":
            return self

        required = ["region", "instance", "host", "database", "user"]
        missing = [f for f in required if not getattr(self, f, None)]

        if missing:
            raise ValueError(
                f"RDS backend requires: {', '.join(missing)}. "
                f"Example: BackendConfig(type='rds', region='us-east-1', "
                f"instance='my-db', host='my-db.xxxxx.us-east-1.rds.amazonaws.com', "
                f"database='agv', user='agv_user', password='secret')"
            )

        # Validate AWS region format (e.g. us-east-1, eu-west-2, ap-southeast-1)
        if self.region and not re.match(r"^[a-z]{2}-[a-z]+-\d+$", self.region):
            raise ValueError(f"Invalid AWS region format: {self.region}")

        # Require either password or IAM auth
        if not self.password and not self.use_iam_auth:
            raise ValueError(
                "RDS backend requires either 'password' or 'use_iam_auth=True'. "
                "For IAM authentication set use_iam_auth=True; for password auth set password."
            )

        # Auto-configure Bedrock embedding defaults for server-side strategy.
        # Requires Aurora PostgreSQL 15.3+ with aws_ml extension.
        if self.embedding_strategy == "server_side":
            if not self.embedding_model:
                self.embedding_model = "amazon.titan-embed-text-v2:0"
            if not self.embedding_dim:
                self.embedding_dim = 1024

        return self

    @model_validator(mode="after")
    def validate_connection_config(self) -> Self:
        """Validate connection configuration conflicts (FR-2.1, AC-17).

        Raises:
            ValueError: If both connection_string and Cloud SQL instance parameters are provided
        """
        # Check for conflicting connection configurations
        has_connection_string = bool(self.connection_string)
        has_cloud_sql_params = bool(self.project and self.instance and self.region)

        if has_connection_string and has_cloud_sql_params:
            raise ValueError(
                "Cannot specify both connection_string and Cloud SQL instance parameters "
                "(project, region, instance). Use one connection method only."
            )

        return self

    @model_validator(mode="after")
    def validate_ssl_config(self) -> Self:
        """Validate SSL configuration (SEC-1).

        Raises:
            ValueError: If ssl_mode="verify-full" without ssl_ca_cert,
                or if ssl_ca_cert file doesn't exist
        """
        # Check if verify-full requires CA cert
        if self.ssl_mode == "verify-full" and not self.ssl_ca_cert:
            raise ValueError(
                "ssl_mode='verify-full' requires ssl_ca_cert path to CA certificate. "
                "Download the server CA certificate from GCP console or use: "
                "gcloud sql ssl-certs describe server-ca --instance=INSTANCE_NAME"
            )

        # Validate CA cert file exists if provided
        if self.ssl_ca_cert:
            import os

            if not os.path.exists(self.ssl_ca_cert):
                raise ValueError(
                    f"CA certificate file not found: {self.ssl_ca_cert}. "
                    f"Please ensure the file exists and the path is correct."
                )

        return self

    def __repr__(self) -> str:
        """Secure repr that masks sensitive credentials.

        Implements SEC-1 requirement: Credentials must not appear in logs.

        Returns:
            String representation with masked credentials

        Example:
            >>> config = BackendConfig(
            ...     type="postgresql",
            ...     connection_string="postgresql://user:secret@host/db"
            ... )
            >>> print(repr(config))
            BackendConfig(type='postgresql', connection_string='***MASKED***', ...)
        """
        parts = [f"type='{self.type}'"]

        # Mask sensitive fields
        if self.connection_string:
            parts.append("connection_string='***MASKED***'")
        if self.database_path:
            parts.append(f"database_path='{self.database_path}'")
        if self.project:
            parts.append(f"project='{self.project}'")
        if self.region:
            parts.append(f"region='{self.region}'")
        if self.instance:
            parts.append(f"instance='{self.instance}'")
        if self.database:
            parts.append(f"database='{self.database}'")
        if self.user:
            parts.append(f"user='{self.user}'")

        # Include non-sensitive config
        parts.append(f"pool_size={self.pool_size}")
        parts.append(f"index_type='{self.index_type}'")
        parts.append(f"fts_language='{self.fts_language}'")

        return f"BackendConfig({', '.join(parts)})"

    def get_display_info(self) -> str:
        """Get a safe display string (without sensitive connection info).

        Returns:
            Human-readable backend description without credentials
        """
        if self.type == "postgresql":
            # Mask connection string credentials
            return f"postgresql (pool_size={self.pool_size})"
        elif self.type in ("lancedb", "sqlite"):
            return f"{self.type} ({self.database_path})"
        elif self.type == "spanner":
            return f"spanner ({self.project_id}/{self.instance_id}/{self.database_id})"
        elif self.type == "cloudsql":
            return f"cloudsql ({self.project}/{self.region}/{self.instance}/{self.database})"
        elif self.type == "alloydb":
            return f"alloydb ({self.project}/{self.region}/{self.cluster}/{self.instance}/{self.database})"
        elif self.type == "rds":
            return f"rds ({self.region}/{self.instance}/{self.database})"
        elif self.type == "memory":
            return "memory (in-memory)"
        return f"{self.type}"


class StorageRoleConfig(BaseModel):
    """Configuration for role-to-backend mapping.

    This model defines which named backend handles each storage role.
    Backend names must reference entries in the backends dictionary.

    Attributes:
        vector_backend: Backend name for vector storage
        graph_backend: Backend name for graph storage
        events_backend: Backend name for event storage
        file_tracker_backend: Backend name for file tracking

    Example:
        >>> roles = StorageRoleConfig(
        ...     vector_backend="primary",
        ...     graph_backend="primary",
        ...     events_backend="sqlite",
        ...     file_tracker_backend="sqlite",
        ... )
    """

    model_config = ConfigDict(
        frozen=False,
        extra="forbid",
        validate_assignment=True,
    )

    vector_backend: str = "default"
    graph_backend: str = "default"
    events_backend: str = "sqlite"
    file_tracker_backend: str = "sqlite"


# Default backend configurations for common setups
DEFAULT_BACKENDS: dict[str, BackendConfig] = {
    "default": BackendConfig(
        type="lancedb",
        database_path="./.agv/lancedb",
    ),
    "sqlite": BackendConfig(
        type="sqlite",
        database_path="./.agv/agent-vault.db",
    ),
}


def create_backend_config(
    backend_type: BackendType,
    **kwargs,
) -> BackendConfig:
    """Factory function to create BackendConfig with sensible defaults.

    Args:
        backend_type: The type of backend to create
        **kwargs: Additional configuration options

    Returns:
        Configured BackendConfig instance

    Raises:
        ValueError: If required fields are missing for the backend type

    Example:
        >>> config = create_backend_config(
        ...     "postgresql",
        ...     connection_string="postgres://localhost/db",
        ... )
    """
    return BackendConfig(type=backend_type, **kwargs)
