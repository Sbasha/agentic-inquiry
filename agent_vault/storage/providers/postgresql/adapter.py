"""PostgreSQL cloud provider adapters.

This module provides an adapter pattern to handle differences between various
PostgreSQL cloud providers (GCP AlloyDB, AWS RDS, Azure Database for PostgreSQL)
particularly regarding server-side embedding generation and extensions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional


class PostgreSQLAdapter(ABC):
    """Base class for PostgreSQL cloud-specific adapters."""

    @property
    @abstractmethod
    def backend_type(self) -> str:
        """Return the backend type identifier (e.g., 'alloydb', 'rds', 'azure')."""

    @property
    def requires_proxy(self) -> bool:
        """Whether this backend typically requires a proxy binary."""
        return False

    @property
    def proxy_type(self) -> Optional[str]:
        """The proxy binary type ('cloud-sql-proxy' or 'alloydb-auth-proxy')."""
        return None

    @abstractmethod
    def required_extensions(
        self, embedding_strategy: str = "local"
    ) -> List[str]:
        """Return the PostgreSQL extensions to install for this provider.

        Strategy-aware so that the cloud-specific ML extensions
        (``aws_ml`` on Aurora, ``azure_ai`` on Azure Postgres,
        ``google_ml_integration`` on AlloyDB) are only required when
        the deployment actually uses them. A plain RDS for PostgreSQL
        deployment running ``embedding_strategy: local`` should not
        try to ``CREATE EXTENSION aws_ml`` — that fails because
        ``aws_ml`` is Aurora-only.

        Args:
            embedding_strategy: ``"local"`` (default) or
                ``"server_side"``. The provider passes its configured
                strategy from ``BackendConfig.embedding_strategy``
                when calling.
        """

    @abstractmethod
    def get_embedding_sql(self, content_sql: str, model: str) -> str:
        """Return SQL fragment for generating an embedding from content.
        
        Args:
            content_sql: SQL expression for the content (e.g. '$1' or 'c.content')
            model: Embedding model name/ID
            
        Returns:
            SQL fragment like "embedding('model', content)::vector"
        """

    @abstractmethod
    async def on_initialize(self, connection: Any) -> None:
        """Perform provider-specific initialization (e.g. creating helper functions)."""

    def get_bulk_embedding_sql(self, table: str, model: str, content_col: str, embedding_col: str) -> Optional[str]:
        """Return SQL for bulk embedding generation if supported.
        
        Returns:
            SQL statement like "CALL ai.initialize_embeddings(...)" or None if not supported.
        """
        return None


class DefaultPostgresAdapter(PostgreSQLAdapter):
    """Default adapter for standard PostgreSQL installations.

    # Supported backend
    Self-hosted PostgreSQL (with ``pgvector``) and GCP Cloud SQL via
    direct DSN — toggled by the ``is_cloudsql`` constructor flag. See
    ``docs/backends/postgresql.md`` and ``docs/backends/cloudsql.md``.
    Contract pinned by
    ``tests/storage/providers/test_postgres_adapter_contracts.py``.
    """

    def __init__(self, is_cloudsql: bool = False):
        self._is_cloudsql = is_cloudsql

    @property
    def backend_type(self) -> str:
        return "cloudsql" if self._is_cloudsql else "postgresql"

    @property
    def requires_proxy(self) -> bool:
        return self._is_cloudsql

    @property
    def proxy_type(self) -> Optional[str]:
        return "cloudsql" if self._is_cloudsql else None

    def required_extensions(
        self, embedding_strategy: str = "local"
    ) -> List[str]:
        # Plain Postgres / CloudSQL via direct DSN: no server-side
        # embedding extension exists, so the strategy argument is
        # ignored — only ``vector`` is required.
        return ["vector"]

    def get_embedding_sql(self, content_sql: str, model: str) -> str:
        # Standard Postgres has no server-side embedding function by default
        raise NotImplementedError("Server-side embeddings not supported on default PostgreSQL")

    async def on_initialize(self, connection: Any) -> None:
        pass


class AlloyDBAdapter(PostgreSQLAdapter):
    """Adapter for Google Cloud AlloyDB.

    # Supported backend
    Google Cloud AlloyDB for PostgreSQL — server-side embedding via
    the ``google_ml_integration`` extension (``embedding(...)``) plus
    the AlloyDB-only bulk path
    (``ai.initialize_embeddings``, ~400 chunks/sec on fresh tables).
    Comparison-and-decision matrix at ``docs/storage-backends.md``;
    a dedicated ``docs/backends/alloydb.md`` is on the audit followup
    list (#167) but not yet written. Contract pinned by
    ``tests/storage/providers/test_postgres_adapter_contracts.py``.
    """

    @property
    def backend_type(self) -> str:
        return "alloydb"

    @property
    def requires_proxy(self) -> bool:
        return True

    @property
    def proxy_type(self) -> str:
        return "alloydb"

    def required_extensions(
        self, embedding_strategy: str = "local"
    ) -> List[str]:
        # ``google_ml_integration`` exposes the in-DB ``embedding(...)``
        # function used for SERVER_SIDE Vertex embeddings. AlloyDB
        # deployments running ``embedding_strategy: local`` (rare, but
        # supported) skip the extension — the indexer embeds
        # client-side and the database doesn't need to call out to
        # Vertex. Default kept as ``"local"`` for consistency with the
        # base class and other adapters; the runtime caller always
        # passes the configured strategy from
        # ``BackendConfig.embedding_strategy`` so the default never
        # actually applies in production.
        if embedding_strategy == "server_side":
            return ["vector", "google_ml_integration"]
        return ["vector"]

    def get_embedding_sql(self, content_sql: str, model: str) -> str:
        return f"embedding('{model}', {content_sql})::vector"

    async def on_initialize(self, connection: Any) -> None:
        pass

    def get_bulk_embedding_sql(self, table: str, model: str, content_col: str, embedding_col: str) -> str:
        return (
            f"CALL ai.initialize_embeddings("
            f"model_id => '{model}', "
            f"table_name => '{table}', "
            f"content_column => '{content_col}', "
            f"embedding_column => '{embedding_col}')"
        )


class RDSAdapter(PostgreSQLAdapter):
    """Adapter for AWS RDS / Aurora PostgreSQL.

    # Supported backend
    AWS RDS for PostgreSQL and Aurora PostgreSQL — see
    ``docs/backends/rds.md`` for setup, embedding strategies (Shape A:
    LOCAL SentenceTransformer; Shape B: client-side Bedrock via
    :class:`~agent_vault.embeddings.bedrock.BedrockEmbedder` from
    RFC 0003; Shape C: Aurora-only server-side Bedrock via
    ``aws_ml``), and authentication. Contract pinned by
    ``tests/storage/providers/test_postgres_adapter_contracts.py``.

    Note: ``aws_ml`` is requested *only* when the backend is
    configured with ``embedding_strategy: server_side`` — that path
    is Aurora-only. Plain RDS for PostgreSQL with
    ``embedding_strategy: local`` (Shape A) skips the extension and
    runs without issue. RFC 0002 tracks the planned ``rds`` /
    ``aurora`` backend-type split that gives each path a distinct
    type identifier.
    """

    def __init__(self, embed_function_name: str = "agv_embed"):
        self.embed_function_name = embed_function_name

    @property
    def backend_type(self) -> str:
        return "rds"

    def required_extensions(
        self, embedding_strategy: str = "local"
    ) -> List[str]:
        # ``aws_ml`` is Aurora-only — only ensure it when the operator
        # has explicitly opted into the server-side path. Plain RDS
        # for PostgreSQL running LOCAL (Shape A in
        # ``docs/backends/rds.md``) and RDS-with-client-side-Bedrock
        # (Shape B) both skip the extension and rely on the indexer
        # to produce vectors.
        if embedding_strategy == "server_side":
            return ["vector", "aws_ml"]
        return ["vector"]

    def get_embedding_sql(self, content_sql: str, model: str) -> str:
        return f"{self.embed_function_name}({content_sql}, '{model}')::vector"

    async def on_initialize(self, connection: Any) -> None:
        # RDS doesn't have a single 'embedding()' function, so we create a wrapper
        # during initialization if server-side embeddings are enabled.
        # This is usually called by the provider when strategy is server_side.
        pass

    async def create_helper_function(self, connection: Any, model: str) -> None:
        """Create the agv_embed helper function for AWS Bedrock."""
        sql = f"""
            CREATE OR REPLACE FUNCTION {self.embed_function_name}(
                content TEXT,
                model_id TEXT DEFAULT '{model}'
            )
            RETURNS vector
            LANGUAGE sql
            VOLATILE
            AS $$
                SELECT (
                    aws_bedrock.invoke_model(
                        model_id := model_id,
                        content_type := 'application/json',
                        accept := 'application/json',
                        model_input := format('{{"inputText": %s}}', to_json(content)::text)
                    )::json->>'embedding'
                )::vector
            $$
        """
        await connection.execute(sql)


class AzurePostgresAdapter(PostgreSQLAdapter):
    """Adapter for Azure Database for PostgreSQL Flexible Server.

    Uses the ``azure_ai`` extension for server-side embeddings via
    Azure OpenAI. The ``model`` argument to ``get_embedding_sql`` is
    the *Azure OpenAI deployment name*, not the upstream OpenAI model
    name — operators name their deployments however they like, but
    matching the deployment to ``text-embedding-3-small`` /
    ``text-embedding-3-large`` is the common convention.

    # Supported backend
    Azure Database for PostgreSQL Flexible Server — see
    ``docs/backends/azure.md`` for setup (CLI commands, ``azure_ai``
    allowlisting, deployment-name dim defaults), authentication
    (managed identity vs. password), and the cost model. Contract
    pinned by
    ``tests/storage/providers/test_postgres_adapter_contracts.py``.
    """

    @property
    def backend_type(self) -> str:
        return "azure"

    def required_extensions(
        self, embedding_strategy: str = "local"
    ) -> List[str]:
        # ``azure_ai`` is the extension that exposes
        # ``azure_ai.generate_embeddings`` for SERVER_SIDE Azure
        # OpenAI calls. A LOCAL Azure deployment (rare — most teams
        # would just use the plain ``postgresql`` backend type in
        # that case) skips the extension. Tracks the cluster-#159
        # ship gate that LOCAL Azure must not error at provider
        # init due to a missing ``azure_ai`` allowlist entry. The
        # default is ``"local"`` for consistency with the base class
        # and the other adapters; the runtime caller always passes
        # the configured strategy.
        if embedding_strategy == "server_side":
            return ["vector", "azure_ai"]
        return ["vector"]

    def get_embedding_sql(self, content_sql: str, model: str) -> str:
        """Return SQL for Azure OpenAI embeddings.
        
        Syntax: azure_ai.generate_embeddings('deployment-name', input_text)
        """
        return f"azure_ai.generate_embeddings('{model}', {content_sql})::vector"

    async def on_initialize(self, connection: Any) -> None:
        """No specific helper functions needed for Azure as it provides a direct function."""
        pass
