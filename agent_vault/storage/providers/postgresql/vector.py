"""PostgreSQL vector storage provider using pgvector.

This module provides a VectorStorageProtocol implementation using PostgreSQL
with the pgvector extension for vector similarity search.

Features:
    - Vector similarity search via pgvector (cosine similarity)
    - Full-text search using PostgreSQL tsvector
    - Hybrid search combining vector and FTS with RRF
    - Project isolation through table prefixes

Requirements:
    - PostgreSQL 12+
    - pgvector extension: CREATE EXTENSION vector;
    - asyncpg: pip install asyncpg
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Union

from agent_vault.database.results import SearchResult
from agent_vault.models.document_chunk import DocumentChunk
from agent_vault.storage.protocols.vector import VectorStorageProtocol
from agent_vault.storage.providers.postgresql.adapter import (
    AlloyDBAdapter,
    AzurePostgresAdapter,
    DefaultPostgresAdapter,
    PostgreSQLAdapter,
    RDSAdapter,
)
from agent_vault.storage.providers.postgresql.connection import (
    PostgresConnectionManager,
)
from agent_vault.models.graph_entity import GraphEntity
from agent_vault.storage.providers.postgresql.entity_rows import row_to_entity
from agent_vault.storage.providers.postgresql.schemas import (
    CHUNK_EMBEDDINGS_TABLE,
    CHUNKS_FTS_TABLE,
    CHUNKS_TABLE,
    ENTITIES_TABLE,
    ENTITY_EMBEDDINGS_TABLE,
    SchemaGenerator,
)
from agent_vault.storage.similarity import (
    distance_to_similarity,
    pgvector_distance_operator,
    pgvector_operator_class,
)

if TYPE_CHECKING:
    import asyncpg
    from agent_vault.database.filters import FilterInput
    from agent_vault.storage.providers.postgresql.index_config import IndexConfig
    from agent_vault.storage.capabilities import ProviderCapabilities

logger = logging.getLogger(__name__)


class TransactionError(Exception):
    """Raised when transaction operations fail."""

    pass


class PostgresVectorProvider(VectorStorageProtocol):
    """PostgreSQL implementation of VectorStorageProtocol.

    Uses pgvector for vector similarity search and PostgreSQL's built-in
    full-text search capabilities. Supports both local and server-side
    embedding strategies via PostgreSQLAdapter implementations.

    Attributes:
        SUPPORTED_ROLES: Roles this provider can fulfill
    """

    SUPPORTED_ROLES = frozenset({"vector"})

    def __init__(
        self,
        connection_manager: PostgresConnectionManager,
        project_id: str,
        *,
        embedding_dim: int = 384,
        index_config: Optional["IndexConfig"] = None,
        fts_language: str = "english",
        embedding_strategy: str = "local",
        embedding_model: Optional[str] = None,
        adapter: Optional[PostgreSQLAdapter] = None,
    ) -> None:
        """Initialize the vector provider.

        Args:
            connection_manager: PostgresConnectionManager instance
            project_id: Project ID for data isolation
            embedding_dim: Vector embedding dimension (default: 384)
            index_config: Optional index configuration.
            fts_language: PostgreSQL FTS language configuration.
            embedding_strategy: "local" or "server_side".
            embedding_model: Server-side embedding model name.
            adapter: Optional cloud-specific adapter (DefaultPostgresAdapter if None).
        """
        from agent_vault.storage.providers.postgresql.index_config import (
            IndexConfig,
            IndexType,
        )

        self._conn = connection_manager
        self._project_id = project_id
        self._embedding_dim = embedding_dim
        self._fts_language = fts_language
        self._initialized = False
        self._embedding_strategy = embedding_strategy
        self._embedding_model = embedding_model
        self._adapter = adapter or DefaultPostgresAdapter()
        self._similarity_metric = connection_manager.similarity_metric
        self._distance_op = pgvector_distance_operator(self._similarity_metric)
        self._vector_op_class = pgvector_operator_class(self._similarity_metric)

        # Index configuration
        if index_config is None:
            index_config = IndexConfig(index_type=IndexType.HNSW)
        self._index_config = index_config

        # Schema generator
        if self._adapter.backend_type == "alloydb":
            from agent_vault.storage.providers.alloydb.schemas import (
                AlloyDBSchemaGenerator,
            )

            self._schema_gen = AlloyDBSchemaGenerator(
                prefix=connection_manager.table_prefix,
                embedding_dim=embedding_dim,
                similarity_metric=self._similarity_metric,
            )
        else:
            self._schema_gen = SchemaGenerator(
                prefix=connection_manager.table_prefix,
                embedding_dim=embedding_dim,
                similarity_metric=self._similarity_metric,
            )

        # Table names
        self._chunks_table = self._schema_gen.get_table_name(CHUNKS_TABLE)
        self._fts_table = self._schema_gen.get_table_name(CHUNKS_FTS_TABLE)
        self._embeddings_table = self._schema_gen.get_table_name(CHUNK_EMBEDDINGS_TABLE)
        # Entity tables are provisioned by ``PostgresGraphProvider``; the
        # vector provider reads from them to serve ``entity_vector_search``
        # because the embedding column is a vector-space concern even though
        # the rest of the entity schema belongs to graph. Table names are
        # derived from the same ``SchemaGenerator`` / prefix as the chunks
        # tables, so no additional configuration is needed.
        self._entities_table = self._schema_gen.get_table_name(ENTITIES_TABLE)
        self._entity_embeddings_table = self._schema_gen.get_table_name(
            ENTITY_EMBEDDINGS_TABLE
        )

        # Transaction support
        self._txn_connection: Optional[asyncpg.Connection] = None

    @property
    def capabilities(self) -> "ProviderCapabilities":
        """Declare this provider's capabilities based on its configuration."""
        from agent_vault.storage.capabilities import (
            EmbeddingStrategy,
            ProviderCapabilities,
        )

        return ProviderCapabilities(
            embedding_strategy=(
                EmbeddingStrategy.SERVER_SIDE
                if self._embedding_strategy == "server_side"
                else EmbeddingStrategy.LOCAL
            ),
            embedding_dimensions=self._embedding_dim,
            embedding_model=self._embedding_model,
            is_postgresql_compatible=True,
            supports_fts=True,
            supports_graph=True,
            backend_type=self._adapter.backend_type,
        )

    def set_transaction_connection(self, connection: asyncpg.Connection) -> None:
        """Set the transaction connection for coordinated operations.

        This method is called by TransactionCoordinator to inject a shared
        connection for atomic multi-provider operations (AC-4, AC-5).

        Args:
            connection: Shared database connection for the transaction

        Raises:
            TransactionError: If already in a transaction

        Example:
            >>> conn = await pool.acquire()
            >>> provider.set_transaction_connection(conn)
            >>> await provider.store_chunks(chunks)  # Uses injected connection
        """
        if self._txn_connection is not None:
            raise TransactionError(
                "Provider already has a transaction connection. "
                "Cannot nest transactions."
            )
        self._txn_connection = connection
        logger.debug("Transaction connection injected into VectorProvider")

    def clear_transaction_connection(self) -> None:
        """Clear the transaction connection after commit/rollback.

        This method is called by TransactionCoordinator after the transaction
        completes (either commit or rollback).

        Example:
            >>> provider.clear_transaction_connection()
            >>> await provider.store_chunks(chunks)  # Uses pool connection
        """
        self._txn_connection = None
        logger.debug("Transaction connection cleared from VectorProvider")

    @property
    def in_transaction(self) -> bool:
        """Check if provider is currently in a transaction.

        Returns:
            True if transaction connection is set, False otherwise
        """
        return self._txn_connection is not None

    async def _get_connection(self) -> asyncpg.Connection:
        """Get connection for database operations.

        Returns the injected transaction connection if in a transaction,
        otherwise acquires a connection from the pool.

        This method implements the connection resolution pattern for
        transaction support (AC-4, AC-5).

        Returns:
            Database connection (either transaction or pool connection)

        Raises:
            PostgresConnectionError: If connection cannot be acquired

        Example:
            >>> conn = await self._get_connection()
            >>> await conn.execute("SELECT 1")
        """
        if self._txn_connection is not None:
            logger.debug("Using transaction connection for VectorProvider operation")
            return self._txn_connection

        # Fall back to pool connection (use ConnectionManager's wrapper)
        # This ensures proper connection acquisition/release
        logger.debug("Using pool connection for VectorProvider operation")
        # For non-transaction operations, use ConnectionManager's methods
        # which handle acquire/release internally
        return None  # Sentinel value meaning "use ConnectionManager"

    async def _execute(self, query: str, *args: Any) -> str:
        """Execute query using transaction-aware connection.

        Args:
            query: SQL query to execute
            *args: Query parameters

        Returns:
            Query status string
        """
        if self._txn_connection is not None:
            return await self._txn_connection.execute(query, *args)
        return await self._conn.execute(query, *args)

    async def _fetch(self, query: str, *args: Any) -> list:
        """Fetch rows using transaction-aware connection.

        Args:
            query: SQL query to execute
            *args: Query parameters

        Returns:
            List of records
        """
        if self._txn_connection is not None:
            return await self._txn_connection.fetch(query, *args)
        return await self._conn.fetch(query, *args)

    async def _fetchrow(self, query: str, *args: Any) -> Optional[Any]:
        """Fetch single row using transaction-aware connection.

        Args:
            query: SQL query to execute
            *args: Query parameters

        Returns:
            Single record or None
        """
        if self._txn_connection is not None:
            return await self._txn_connection.fetchrow(query, *args)
        return await self._conn.fetchrow(query, *args)

    async def _fetchval(self, query: str, *args: Any) -> Any:
        """Fetch single value using transaction-aware connection.

        Args:
            query: SQL query to execute
            *args: Query parameters

        Returns:
            Single value
        """
        if self._txn_connection is not None:
            return await self._txn_connection.fetchval(query, *args)
        return await self._conn.fetchval(query, *args)

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        project_id: str,
    ) -> "PostgresVectorProvider":
        """Create provider from configuration dict.

        Args:
            config: Configuration with connection_string or cloud params
            project_id: Project ID for data isolation

        Returns:
            Configured PostgresVectorProvider instance
        """
        from agent_vault.storage.providers.postgresql.index_config import (
            IndexConfig,
            IndexType,
            HNSWParams,
            IVFFlatParams,
        )

        # 1. Resolve Adapter
        backend_type = config.get("type", "postgresql")
        logger.info("Resolving adapter for backend_type: %s", backend_type)
        if backend_type == "alloydb":
            adapter = AlloyDBAdapter()
        elif backend_type == "cloudsql":
            adapter = DefaultPostgresAdapter(is_cloudsql=True)
        elif backend_type == "rds":
            adapter = RDSAdapter()
        elif backend_type == "azure":
            adapter = AzurePostgresAdapter()
        else:
            adapter = DefaultPostgresAdapter()

        # 2. Build connection string
        resolved_config = dict(config)
        if backend_type == "alloydb":
            from agent_vault.storage.providers.alloydb import AlloyDBConnectionManager

            manager = AlloyDBConnectionManager.from_config(resolved_config)
        else:
            if not resolved_config.get("connection_string"):
                if backend_type == "rds":
                    resolved_config["connection_string"] = cls._build_rds_dsn(config)
                else:
                    resolved_config["connection_string"] = cls._build_dsn_from_config(
                        config
                    )

            manager = PostgresConnectionManager.from_config(
                resolved_config,
                table_prefix=config.get("table_prefix", "agv_"),
            )

        # 3. Build IndexConfig
        index_config = None
        if "index_type" in config or "index_params" in config:
            index_type_str = config.get("index_type", "hnsw")
            index_type = IndexType(index_type_str)

            hnsw_params = None
            ivfflat_params = None
            index_params = config.get("index_params")

            if index_type == IndexType.HNSW and index_params:
                hnsw_params = HNSWParams(**index_params)
            elif index_type == IndexType.IVFFLAT and index_params:
                ivfflat_params = IVFFlatParams(**index_params)

            index_config = IndexConfig(
                index_type=index_type,
                hnsw_params=hnsw_params,
                ivfflat_params=ivfflat_params,
                expected_rows=config.get("expected_rows"),
            )

        # 4. Resolve embedding strategy and dimensions
        default_strategy = "server_side" if backend_type == "alloydb" else "local"
        embedding_strategy = config.get("embedding_strategy", default_strategy)
        embedding_model = config.get("embedding_model")

        # Default dims based on provider defaults if not specified
        default_dim = 384
        if embedding_strategy == "server_side":
            if backend_type == "rds":
                default_dim = 1024  # Titan default
            elif backend_type == "alloydb":
                default_dim = 768  # text-embedding-005 default

        embedding_dim = config.get("embedding_dim", default_dim)

        return cls(
            manager,
            project_id,
            embedding_dim=embedding_dim,
            index_config=index_config,
            fts_language=config.get("fts_language", "english"),
            embedding_strategy=embedding_strategy,
            embedding_model=embedding_model,
            adapter=adapter,
        )

    @staticmethod
    def _build_rds_dsn(config: Dict[str, Any]) -> str:
        """Build a PostgreSQL DSN for direct RDS connection."""
        from urllib.parse import quote

        user = config.get("user", "postgres")
        password = config.get("password")
        host = config.get("host", "localhost")
        port = config.get("port", 5432)
        database = config.get("database", "agent-vault")
        ssl_mode = config.get("ssl_mode", "require")

        if password:
            dsn = f"postgresql://{user}:{quote(str(password), safe='')}@{host}:{port}/{database}"
        else:
            dsn = f"postgresql://{user}@{host}:{port}/{database}"

        if ssl_mode:
            dsn += f"?sslmode={ssl_mode}"
        return dsn

    @staticmethod
    def _build_dsn_from_config(config: Dict[str, Any]) -> str:
        """Build a PostgreSQL DSN from configuration parameters.

        When a ``host`` field is present (e.g. RDS direct connections), it is
        used as the database host.  Otherwise falls back to 127.0.0.1, which
        is the address expected by the AlloyDB Auth Proxy and Cloud SQL Proxy
        running on localhost.

        Args:
            config: Dict with user, password, port, database, and optionally
                host (for direct connections) and ssl_mode fields

        Returns:
            PostgreSQL connection string
        """
        from urllib.parse import quote

        user = config.get("user", "postgres")
        password = config.get("password")
        port = config.get("port", 5432)
        database = config.get("database", "agent-vault")
        # Use explicit host when provided (RDS direct); default to proxy address
        host = config.get("host", "127.0.0.1")
        ssl_mode = config.get("ssl_mode")

        if password:
            dsn = f"postgresql://{user}:{quote(str(password), safe='')}@{host}:{port}/{database}"
        else:
            dsn = f"postgresql://{user}@{host}:{port}/{database}"

        if ssl_mode:
            dsn += f"?sslmode={ssl_mode}"

        return dsn

    # =========================================================================
    # Lifecycle Methods
    # =========================================================================

    async def initialize(self) -> None:
        """Initialize the storage backend."""
        if self._initialized:
            return

        await self._conn.initialize()

        # Ensure required extensions are installed via adapter.
        # The adapter filters its extension list based on the configured
        # embedding strategy — plain RDS LOCAL skips ``aws_ml`` (Aurora
        # only); LOCAL Azure skips ``azure_ai``; LOCAL AlloyDB skips
        # ``google_ml_integration``. Without this, a Shape A RDS
        # deployment (LOCAL) would fail at ``CREATE EXTENSION aws_ml``.
        for ext in self._adapter.required_extensions(self._embedding_strategy):
            await self._conn.ensure_extension(ext)

        # Adapter-specific initialization (e.g. creating helper functions)
        if self._embedding_strategy == "server_side":
            if isinstance(self._adapter, RDSAdapter):
                model = self._embedding_model or "amazon.titan-embed-text-v2:0"
                await self._adapter.create_helper_function(self._conn, model)
            else:
                await self._adapter.on_initialize(self._conn)

        # Dimension mismatch detection at startup
        from agent_vault.storage.providers.postgresql.schema_tracker import (
            SchemaVersionTracker,
            SchemaMismatchError,
        )

        tracker = SchemaVersionTracker(self._conn)
        await tracker.ensure_meta_table()

        # Check for dimension mismatch before proceeding
        mismatch = await tracker.detect_dimension_mismatch(
            self._chunks_table, self._embedding_dim
        )

        if mismatch:
            error_msg = (
                f"Embedding dimension mismatch detected.\n"
                f"  Configured: {mismatch.configured} dimensions\n"
                f"  Existing table '{mismatch.table_name}': {mismatch.actual} dimensions\n"
                f"\n"
                f"To migrate, run: agv schema migrate --project {self._project_id} "
                f"--confirm-data-loss\n"
                f"This will drop and recreate the embedding column, requiring full re-indexing."
            )
            logger.error(error_msg)
            raise SchemaMismatchError(error_msg)

        # Create tables (without vector indexes - we'll create those with config)
        # Create chunks table
        chunks_create_stmt = self._schema_gen.generate_create_table(CHUNKS_TABLE)
        await self._conn.execute(chunks_create_stmt)

        # Create FTS table
        fts_create_stmt = self._schema_gen.generate_create_table(CHUNKS_FTS_TABLE)
        await self._conn.execute(fts_create_stmt)

        # Create non-vector indexes (project, file, content_type)
        from asyncpg.utils import _quote_ident as escape_identifier

        table_ident = escape_identifier(self._chunks_table)
        await self._conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{self._chunks_table}_project ON {table_ident}(project_id);"
        )
        await self._conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{self._chunks_table}_file ON {table_ident}(file_path);"
        )
        await self._conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{self._chunks_table}_content_type ON {table_ident}(content_type);"
        )

        # Create FTS indexes
        fts_ident = escape_identifier(self._fts_table)
        await self._conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{self._fts_table}_project ON {fts_ident}(project_id);"
        )
        await self._conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{self._fts_table}_content ON {fts_ident} USING GIN(tsvector_content);"
        )

        # Create separate embeddings table for server-side embedding strategy
        if self._embedding_strategy == "server_side":
            embeddings_create_stmt = self._schema_gen.generate_create_table(
                CHUNK_EMBEDDINGS_TABLE
            )
            await self._conn.execute(embeddings_create_stmt)

            embeddings_ident = escape_identifier(self._embeddings_table)
            await self._conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self._embeddings_table}_project "
                f"ON {embeddings_ident}(project_id);"
            )

        # Query current row count for dynamic lists calculation (AC-2)
        row_count_query = f"SELECT COUNT(*) FROM {table_ident}"
        try:
            row_count = await self._conn.fetchval(row_count_query)
        except Exception as e:
            logger.warning(f"Could not query row count, defaulting to 0: {e}")
            row_count = 0

        # Create vector index with configured type (AC-1, AC-2)
        index_sql = self._schema_gen.generate_vector_index(
            table_name=self._chunks_table,
            column_name="embedding",
            index_config=self._index_config,
            row_count=row_count,
        )

        if index_sql:  # Only create if not IndexType.NONE
            logger.info(
                f"Creating vector index: type={self._index_config.index_type.value}, "
                f"row_count={row_count}"
            )
            await self._conn.execute(index_sql)

        self._initialized = True
        logger.info(
            f"PostgresVectorProvider initialized for project: {self._project_id}, "
            f"index_type: {self._index_config.index_type.value}"
        )

    async def close(self) -> None:
        """Close the storage backend connection.

        Releases resources. Safe to call multiple times.
        """
        # Connection manager is shared, don't close it here
        self._initialized = False
        logger.debug("PostgresVectorProvider closed for project: %s", self._project_id)

    # =========================================================================
    # Core CRUD Operations
    # =========================================================================

    # Default batch size for chunk inserts
    CHUNK_BATCH_SIZE = 1000

    async def upsert_chunks(
        self,
        chunks: Sequence[DocumentChunk],
        project_id: str,
    ) -> int:
        """Insert or update document chunks using batch inserts.

        Uses executemany() for performance — processes chunks in batches
        instead of individual SQL statements per chunk.

        When embedding_strategy="server_side", the embedding column is
        inserted as NULL. Embeddings are populated separately via
        ai.initialize_embeddings() or similar server-side mechanism.

        Args:
            chunks: Sequence of DocumentChunk objects
            project_id: Project scope for isolation

        Returns:
            Number of chunks upserted
        """
        if not chunks:
            return 0

        # Validate project_id consistency upfront
        for chunk in chunks:
            if chunk.project_id != project_id:
                raise ValueError(
                    f"Chunk project_id mismatch: {chunk.project_id} != {project_id}"
                )

        server_side = self._embedding_strategy == "server_side"

        if server_side:
            # Server-side: skip embedding column entirely
            chunk_sql = f"""
                INSERT INTO {self._chunks_table} (
                    id, project_id, file_path, chunk_index, content,
                    content_type, language, start_line, end_line,
                    metadata, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $11)
                ON CONFLICT (id)
                DO UPDATE SET
                    content = EXCLUDED.content,
                    content_type = EXCLUDED.content_type,
                    language = EXCLUDED.language,
                    start_line = EXCLUDED.start_line,
                    end_line = EXCLUDED.end_line,
                    metadata = EXCLUDED.metadata,
                    updated_at = EXCLUDED.updated_at
            """
        else:
            chunk_sql = f"""
                INSERT INTO {self._chunks_table} (
                    id, project_id, file_path, chunk_index, content,
                    content_type, language, start_line, end_line,
                    embedding, metadata, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::vector, $11, $12, $12)
                ON CONFLICT (id)
                DO UPDATE SET
                    content = EXCLUDED.content,
                    content_type = EXCLUDED.content_type,
                    language = EXCLUDED.language,
                    start_line = EXCLUDED.start_line,
                    end_line = EXCLUDED.end_line,
                    embedding = EXCLUDED.embedding,
                    metadata = EXCLUDED.metadata,
                    updated_at = EXCLUDED.updated_at
            """

        count = 0

        # FTS uses two stemmer configs: 'simple' for CODE, configured language for docs.
        # Since executemany requires a single SQL statement, we split chunks by content_type
        # and run separate batches for code vs docs.
        code_fts_sql = f"""
            INSERT INTO {self._fts_table} (
                chunk_id, project_id, tsvector_content
            ) VALUES (
                $1, $2,
                to_tsvector('simple', $3) ||
                to_tsvector('simple', regexp_replace(coalesce($4, ''), '[/._\\-]', ' ', 'g'))
            )
            ON CONFLICT (chunk_id)
            DO UPDATE SET tsvector_content =
                to_tsvector('simple', $3) ||
                to_tsvector('simple', regexp_replace(coalesce($4, ''), '[/._\\-]', ' ', 'g'))
        """
        doc_fts_sql = f"""
            INSERT INTO {self._fts_table} (
                chunk_id, project_id, tsvector_content
            ) VALUES (
                $1, $2,
                to_tsvector('{self._fts_language}', $3) ||
                to_tsvector('simple', regexp_replace(coalesce($4, ''), '[/._\\-]', ' ', 'g'))
            )
            ON CONFLICT (chunk_id)
            DO UPDATE SET tsvector_content =
                to_tsvector('{self._fts_language}', $3) ||
                to_tsvector('simple', regexp_replace(coalesce($4, ''), '[/._\\-]', ' ', 'g'))
        """

        # Process in batches
        batch_size = self.CHUNK_BATCH_SIZE
        for batch_start in range(0, len(chunks), batch_size):
            batch = chunks[batch_start : batch_start + batch_size]
            now = datetime.now(timezone.utc)

            if server_side:
                chunk_args = [
                    (
                        chunk.id,
                        project_id,
                        chunk.file_path,
                        chunk.chunk_index,
                        chunk.content,
                        chunk.content_type,
                        chunk.language or None,
                        chunk.line_start if chunk.line_start >= 0 else None,
                        chunk.line_end if chunk.line_end >= 0 else None,
                        json.dumps(chunk.metadata),
                        now,
                    )
                    for chunk in batch
                ]
            else:
                chunk_args = [
                    (
                        chunk.id,
                        project_id,
                        chunk.file_path,
                        chunk.chunk_index,
                        chunk.content,
                        chunk.content_type,
                        chunk.language or None,
                        chunk.line_start if chunk.line_start >= 0 else None,
                        chunk.line_end if chunk.line_end >= 0 else None,
                        f"[{','.join(str(v) for v in chunk.vector)}]",
                        json.dumps(chunk.metadata),
                        now,
                    )
                    for chunk in batch
                ]

            # Split FTS args by content type for correct stemmer
            code_fts_args = [
                (chunk.id, project_id, chunk.fts_text, chunk.file_path)
                for chunk in batch
                if chunk.content_type == "CODE"
            ]
            doc_fts_args = [
                (chunk.id, project_id, chunk.fts_text, chunk.file_path)
                for chunk in batch
                if chunk.content_type != "CODE"
            ]

            async with self._conn.transaction() as conn:
                await conn.executemany(chunk_sql, chunk_args)
                if code_fts_args:
                    await conn.executemany(code_fts_sql, code_fts_args)
                if doc_fts_args:
                    await conn.executemany(doc_fts_sql, doc_fts_args)

            count += len(batch)

        logger.debug("Upserted %d chunks for project %s (batched)", count, project_id)
        return count

    async def delete_chunks_by_file(self, file_path: str, project_id: str) -> int:
        """Delete all chunks from a specific file.

        Args:
            file_path: Path to the source file
            project_id: Project scope for isolation

        Returns:
            Number of chunks deleted
        """
        # FTS entries cascade delete via foreign key
        result = await self._execute(
            f"""
            DELETE FROM {self._chunks_table}
            WHERE project_id = $1 AND file_path = $2
            """,
            project_id,
            file_path,
        )
        # Parse "DELETE N" result
        count = int(result.split()[-1]) if result else 0
        logger.debug("Deleted %d chunks from %s", count, file_path)
        return count

    async def delete_chunks_by_ids(
        self,
        chunk_ids: List[str],
        project_id: str,
    ) -> int:
        """Delete chunks by their IDs.

        Args:
            chunk_ids: List of chunk IDs to delete
            project_id: Project scope for isolation

        Returns:
            Number of chunks deleted
        """
        if not chunk_ids:
            return 0

        # FTS entries cascade delete via foreign key
        result = await self._execute(
            f"""
            DELETE FROM {self._chunks_table}
            WHERE project_id = $1 AND id = ANY($2)
            """,
            project_id,
            chunk_ids,
        )
        count = int(result.split()[-1]) if result else 0
        logger.debug("Deleted %d chunks by ID", count)
        return count

    async def get_chunks_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> List[DocumentChunk]:
        """Get all chunks from a specific file.

        Args:
            file_path: Path to the source file
            project_id: Project scope for isolation

        Returns:
            List of DocumentChunk objects
        """
        rows = await self._fetch(
            f"""
            SELECT * FROM {self._chunks_table}
            WHERE project_id = $1 AND file_path = $2
            ORDER BY chunk_index
            """,
            project_id,
            file_path,
        )
        return [self._row_to_chunk(row) for row in rows]

    # =========================================================================
    # Search Operations
    # =========================================================================

    async def vector_search(
        self,
        query_vector: Union[List[float], str],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Perform vector similarity search.

        Accepts either a pre-computed vector (list of floats) or raw query
        text (str). When embedding_strategy="server_side" and query_vector
        is a string, the database generates the query embedding server-side.

        Args:
            query_vector: Query embedding vector (list of floats) or query
                text (str, for server-side embedding)
            limit: Maximum number of results
            filters: Optional metadata filters
            project_id: Optional project scope

        Returns:
            List of SearchResult objects ranked by similarity
        """
        # Server-side embedding: accept raw text query
        if isinstance(query_vector, str) and self._embedding_strategy == "server_side":
            return await self._text_vector_search(
                query_vector, limit, filters, project_id
            )

        # Server-side with pre-computed vector: JOIN with embeddings table
        if self._embedding_strategy == "server_side":
            return await self._precomputed_vector_search_server_side(
                query_vector, limit, filters, project_id
            )

        vector_str = f"[{','.join(str(v) for v in query_vector)}]"
        pid = project_id or self._project_id

        # Build filter clause - param_offset=3 because we have $1=vector, $2=project_id, $3=limit
        filter_clause, filter_params = self._build_filter_clause(
            filters, param_offset=3
        )

        query = f"""
            SELECT *, (embedding {self._distance_op} $1::vector) as _distance
            FROM {self._chunks_table}
            WHERE project_id = $2 {filter_clause}
            ORDER BY embedding {self._distance_op} $1::vector
            LIMIT $3
        """
        params = [vector_str, pid, limit, *filter_params]

        rows = await self._fetch(query, *params)
        return [self._row_to_search_result(row, "vector") for row in rows]

    async def _text_vector_search(
        self,
        query_text: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Vector search using server-side embedding generation via adapter."""
        pid = project_id or self._project_id
        # Use adapter-specific default model if not provided
        if self._embedding_model:
            model = self._embedding_model
        elif isinstance(self._adapter, RDSAdapter):
            model = "amazon.titan-embed-text-v2:0"
        else:
            model = "text-embedding-005"

        # param_offset=3 because $1=query_text, $2=project_id, $3=limit
        filter_clause, filter_params = self._build_filter_clause(
            filters, param_offset=3, table_alias="c"
        )

        embedding_sql = self._adapter.get_embedding_sql("$1", model)

        # All server-side embedding backends use the separate embeddings table.
        # AlloyDB previously queried c.embedding directly, but server-side
        # embeddings are stored in agv_v_chunk_embeddings (not on the chunks table).
        if self._adapter.backend_type == "alloydb":
            query = f"""
                WITH query_vec AS (
                    SELECT {embedding_sql} AS vec
                )
                SELECT
                    c.id, c.project_id, c.file_path, c.chunk_index, c.content,
                    c.content_type, c.language, c.start_line, c.end_line,
                    c.metadata, c.created_at, c.updated_at,
                    (e.embedding {self._distance_op} (SELECT vec FROM query_vec)) AS _distance
                FROM {self._chunks_table} c
                JOIN {self._embeddings_table} e ON e.chunk_id = c.id
                WHERE c.project_id = $2
                  AND e.project_id = $2
                  AND e.embedding IS NOT NULL
                  {filter_clause}
                ORDER BY e.embedding {self._distance_op} (SELECT vec FROM query_vec)
                LIMIT $3
            """
        else:
            query = f"""
                WITH query_vec AS (
                    SELECT {embedding_sql} AS vec
                )
                SELECT
                    c.id, c.project_id, c.file_path, c.chunk_index, c.content,
                    c.content_type, c.language, c.start_line, c.end_line,
                    c.metadata, c.created_at, c.updated_at,
                    (e.embedding {self._distance_op} (SELECT vec FROM query_vec)) AS _distance
                FROM {self._chunks_table} c
                JOIN {self._embeddings_table} e ON e.chunk_id = c.id
                WHERE c.project_id = $2
                  AND e.project_id = $2
                  AND e.embedding IS NOT NULL
                  {filter_clause}
                ORDER BY e.embedding {self._distance_op} (SELECT vec FROM query_vec)
                LIMIT $3
            """
        params = [query_text, pid, limit, *filter_params]

        rows = await self._fetch(query, *params)
        return [self._row_to_search_result(row, "vector") for row in rows]

    async def _precomputed_vector_search_server_side(
        self,
        query_vector: Any,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Vector search using a pre-computed vector with the server-side embeddings table.

        Used when embedding_strategy="server_side" but the caller has already computed
        a query embedding locally. JOINs the separate embeddings table since the
        chunks table has no populated embedding column in server-side mode.

        Args:
            query_vector: Pre-computed query embedding as a list of floats
            limit: Maximum number of results
            filters: Optional metadata filters
            project_id: Optional project scope

        Returns:
            List of SearchResult objects ranked by similarity
        """
        pid = project_id or self._project_id
        vector_str = f"[{','.join(str(v) for v in query_vector)}]"

        # param_offset=3 because $1=vector, $2=project_id, $3=limit
        filter_clause, filter_params = self._build_filter_clause(
            filters, param_offset=3, table_alias="c"
        )

        query = f"""
            SELECT
                c.id, c.project_id, c.file_path, c.chunk_index, c.content,
                c.content_type, c.language, c.start_line, c.end_line,
                c.metadata, c.created_at, c.updated_at,
                (e.embedding {self._distance_op} $1::vector) AS _distance
            FROM {self._chunks_table} c
            JOIN {self._embeddings_table} e ON e.chunk_id = c.id
            WHERE c.project_id = $2
              AND e.project_id = $2
              AND e.embedding IS NOT NULL
              {filter_clause}
            ORDER BY e.embedding {self._distance_op} $1::vector
            LIMIT $3
        """
        params = [vector_str, pid, limit, *filter_params]

        rows = await self._fetch(query, *params)
        return [self._row_to_search_result(row, "vector") for row in rows]

    # Compiled regex for CamelCase splitting in FTS queries
    _CAMEL_LOWER_UPPER = re.compile(r"(?<=[a-z])(?=[A-Z])")
    _CAMEL_UPPER_UPPER_LOWER = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")

    # Common stop words to remove from OR-based FTS queries
    _FTS_STOP_WORDS = frozenset(
        {
            "a",
            "an",
            "the",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "do",
            "does",
            "did",
            "have",
            "has",
            "had",
            "how",
            "what",
            "when",
            "where",
            "which",
            "who",
            "whom",
            "this",
            "that",
            "and",
            "or",
            "but",
            "if",
            "for",
            "of",
            "to",
            "in",
            "on",
            "at",
            "by",
            "with",
            "from",
            "it",
            "its",
            "can",
            "will",
        }
    )

    def _preprocess_fts_query(self, query: str) -> str:
        """Preprocess FTS query for better recall.

        Applies CamelCase/snake_case splitting and builds an OR-augmented
        query that matches ANY significant term. The original query is
        included first for AND matching (higher precision), followed by
        an OR variant for broader recall.

        Args:
            query: Raw search query

        Returns:
            Preprocessed query with split identifiers
        """
        # Split CamelCase and snake_case identifiers
        parts = query.replace("_", " ").replace("-", " ")
        parts = self._CAMEL_LOWER_UPPER.sub(" ", parts)
        parts = self._CAMEL_UPPER_UPPER_LOWER.sub(" ", parts)

        # If CamelCase splitting added words, include both forms
        if parts != query:
            return f"{parts} {query}"
        return parts

    def _build_or_tsquery(self, query: str) -> str:
        """Build an OR-based tsquery expression from query terms.

        Extracts significant words (removing stop words), applies CamelCase
        splitting, and joins with OR for broader FTS recall.

        Args:
            query: Raw search query

        Returns:
            SQL expression for OR-based tsquery, e.g. "'word1' | 'word2' | 'word3'"
            Returns empty string if no significant terms found.
        """
        # Apply CamelCase/snake_case splitting first
        expanded = self._preprocess_fts_query(query)

        # Tokenize and filter
        words = re.split(r"\s+", expanded)
        significant = []
        for w in words:
            w_clean = re.sub(r"[^a-zA-Z0-9]", "", w)
            if (
                w_clean
                and w_clean.lower() not in self._FTS_STOP_WORDS
                and len(w_clean) >= 2
            ):
                significant.append(w_clean)

        if not significant:
            return ""

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for w in significant:
            w_lower = w.lower()
            if w_lower not in seen:
                seen.add(w_lower)
                unique.append(w)

        # Terms must NOT be quoted so to_tsquery() can stem them
        # e.g., "Eligibility" → "elig" with english stemmer
        return " | ".join(unique)

    async def fts_search(
        self,
        query: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Perform full-text search with OR-augmented recall.

        Uses a two-tier query strategy:
        1. AND query (plainto_tsquery): High precision for exact multi-term matches
        2. OR query (to_tsquery with |): Broader recall when AND matches are scarce

        Both tiers search with 'simple' (code, no stemming) and configured
        language (docs, with stemming). Results are deduplicated by chunk ID.

        Args:
            query: Search query string
            limit: Maximum number of results
            filters: Optional metadata filters
            project_id: Optional project scope

        Returns:
            List of SearchResult objects ranked by relevance
        """
        pid = project_id or self._project_id

        # Preprocess query: split CamelCase identifiers
        preprocessed = self._preprocess_fts_query(query)

        # Build filter clause for chunks table - param_offset varies by query variant
        filter_clause, filter_params = self._build_filter_clause(
            filters, param_offset=4, table_alias="c"
        )

        # Build OR tsquery for broader recall
        or_expr = self._build_or_tsquery(query)

        if or_expr:
            # Two-tier FTS: AND query (high precision) UNION OR query (broad recall)
            # AND results get 2x rank boost to maintain precision advantage
            query_sql = f"""
                WITH and_results AS (
                    SELECT c.*, f.tsvector_content,
                        ts_rank(f.tsvector_content,
                            plainto_tsquery('simple', $1) || plainto_tsquery('{self._fts_language}', $1)
                        ) * 2.0 as rank
                    FROM {self._chunks_table} c
                    JOIN {self._fts_table} f ON f.chunk_id = c.id
                    WHERE c.project_id = $2
                      AND f.tsvector_content @@ (
                          plainto_tsquery('simple', $1) || plainto_tsquery('{self._fts_language}', $1)
                      )
                      {filter_clause}
                ),
                or_results AS (
                    SELECT c.*, f.tsvector_content,
                        ts_rank(f.tsvector_content,
                            to_tsquery('simple', $3) || to_tsquery('{self._fts_language}', $3)
                        ) as rank
                    FROM {self._chunks_table} c
                    JOIN {self._fts_table} f ON f.chunk_id = c.id
                    WHERE c.project_id = $2
                      AND f.tsvector_content @@ (
                          to_tsquery('simple', $3) || to_tsquery('{self._fts_language}', $3)
                      )
                      {filter_clause}
                ),
                combined AS (
                    SELECT * FROM and_results
                    UNION ALL
                    SELECT * FROM or_results
                )
                SELECT DISTINCT ON (id) *
                FROM combined
                ORDER BY id, rank DESC
            """
            # Re-sort by rank after dedup
            query_sql = f"""
                SELECT * FROM ({query_sql}) sub
                ORDER BY rank DESC
                LIMIT $4
            """
            params = [preprocessed, pid, or_expr, limit, *filter_params]
        else:
            # Fallback: simple AND query with preprocessed terms
            query_sql = f"""
                SELECT c.*,
                    ts_rank(f.tsvector_content,
                        plainto_tsquery('simple', $1) || plainto_tsquery('{self._fts_language}', $1)
                    ) as rank
                FROM {self._chunks_table} c
                JOIN {self._fts_table} f ON f.chunk_id = c.id
                WHERE c.project_id = $2
                  AND f.tsvector_content @@ (
                      plainto_tsquery('simple', $1) || plainto_tsquery('{self._fts_language}', $1)
                  )
                  {filter_clause}
                ORDER BY rank DESC
                LIMIT $3
            """
            params = [preprocessed, pid, limit, *filter_params]
            # Adjust filter param_offset for 3-param variant
            filter_clause, filter_params = self._build_filter_clause(
                filters, param_offset=3, table_alias="c"
            )
            query_sql = f"""
                SELECT c.*,
                    ts_rank(f.tsvector_content,
                        plainto_tsquery('simple', $1) || plainto_tsquery('{self._fts_language}', $1)
                    ) as rank
                FROM {self._chunks_table} c
                JOIN {self._fts_table} f ON f.chunk_id = c.id
                WHERE c.project_id = $2
                  AND f.tsvector_content @@ (
                      plainto_tsquery('simple', $1) || plainto_tsquery('{self._fts_language}', $1)
                  )
                  {filter_clause}
                ORDER BY rank DESC
                LIMIT $3
            """
            params = [preprocessed, pid, limit, *filter_params]

        rows = await self._fetch(query_sql, *params)
        return [self._row_to_search_result(row, "fts") for row in rows]

    async def hybrid_search(
        self,
        query_vector: List[float],
        query_text: str,
        limit: int = 10,
        vector_weight: float = 0.7,
        project_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Perform hybrid vector + FTS search using RRF.

        Args:
            query_vector: Query embedding vector
            query_text: Query text for FTS
            limit: Maximum number of results
            vector_weight: Weight for vector results (0.0-1.0)
            project_id: Optional project scope

        Returns:
            List of SearchResult objects with combined ranking
        """
        # Get more candidates from each source for better fusion
        candidate_limit = min(limit * 3, 100)

        vector_results = await self.vector_search(
            query_vector, limit=candidate_limit, project_id=project_id
        )
        fts_results = await self.fts_search(
            query_text, limit=candidate_limit, project_id=project_id
        )

        # Reciprocal Rank Fusion
        fts_weight = 1.0 - vector_weight
        k = 60  # RRF constant

        scores: Dict[str, float] = {}
        data: Dict[str, Dict[str, Any]] = {}

        # Add vector scores
        for rank, result in enumerate(vector_results, 1):
            rrf_score = vector_weight / (k + rank)
            scores[result.id] = scores.get(result.id, 0) + rrf_score
            data[result.id] = result.data

        # Add FTS scores
        for rank, result in enumerate(fts_results, 1):
            rrf_score = fts_weight / (k + rank)
            scores[result.id] = scores.get(result.id, 0) + rrf_score
            if result.id not in data:
                data[result.id] = result.data

        # Sort by combined score and normalize
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[
            :limit
        ]
        max_score = max(scores.values()) if scores else 1.0

        return [
            SearchResult(
                id=doc_id,
                data=data[doc_id],
                score=min(scores[doc_id] / max_score, 1.0),
                source="hybrid",
            )
            for doc_id in sorted_ids
        ]

    # =========================================================================
    # Query Operations
    # =========================================================================

    async def query(
        self,
        filters: Dict[str, Any],
        limit: int = 100,
        offset: int = 0,
        project_id: Optional[str] = None,
    ) -> List[DocumentChunk]:
        """Query chunks with filters.

        Args:
            filters: Filter conditions
            limit: Maximum results
            offset: Pagination offset
            project_id: Optional project scope

        Returns:
            List of matching DocumentChunk objects
        """
        pid = project_id or self._project_id
        filter_clause, filter_params = self._build_filter_clause(
            filters, param_offset=1
        )

        # Dynamically compute LIMIT/OFFSET param numbers after filter params
        limit_param = len(filter_params) + 2  # $1 is project_id, filters start at $2
        offset_param = len(filter_params) + 3

        query = f"""
            SELECT * FROM {self._chunks_table}
            WHERE project_id = $1 {filter_clause}
            ORDER BY chunk_index
            LIMIT ${limit_param} OFFSET ${offset_param}
        """
        params = [pid, *filter_params, limit, offset]

        rows = await self._fetch(query, *params)
        return [self._row_to_chunk(row) for row in rows]

    # =========================================================================
    # Entity Vector Search
    # =========================================================================

    async def entity_vector_search(
        self,
        query_vector: Union[str, List[float]],
        project_id: str,
        limit: int = 50,
        entity_type: Optional[str] = None,
    ) -> List[GraphEntity]:
        """Search entities by pgvector similarity.

        The entity schema (``g_entities`` / ``g_entity_embeddings``) is
        provisioned by :class:`PostgresGraphProvider`, but vector similarity
        is a vector-space op — so it lives here and reads through the
        shared connection pool. Table names are derived from the same
        ``SchemaGenerator`` as the chunks tables; no new config required.

        For server-side embedding backends (AlloyDB, RDS server-side) a
        raw ``str`` query_vector is accepted and routed through the
        adapter's embedding function; otherwise ``query_vector`` must be
        a list of floats matching the stored embedding dim.
        """
        # ``str`` input is only valid when this provider is configured for
        # server-side embedding. Otherwise it would silently fall through
        # to ``','.join(str(v) for v in query_vector)`` which iterates the
        # string character-by-character and produces nonsense SQL. Reject
        # it early per the protocol's "SHOULD raise for str input" clause.
        if (
            isinstance(query_vector, str)
            and self._embedding_strategy != "server_side"
        ):
            raise TypeError(
                "PostgresVectorProvider only accepts a str query_vector "
                "when embedding_strategy='server_side' (AlloyDB / RDS with "
                "aws_ml); got str with embedding_strategy="
                f"{self._embedding_strategy!r}."
            )

        if isinstance(query_vector, str) and self._embedding_strategy == "server_side":
            if self._embedding_model:
                model = self._embedding_model
            elif isinstance(self._adapter, RDSAdapter):
                model = "amazon.titan-embed-text-v2:0"
            else:
                model = "text-embedding-005"

            type_clause = ""
            params: list = [query_vector, project_id, limit]
            if entity_type:
                type_clause = " AND ent.entity_type = $4"
                params.append(entity_type)

            embedding_sql = self._adapter.get_embedding_sql("$1", model)
            # ``emb.embedding AS embedding`` is required so ``row_to_entity``
            # hydrates ``GraphEntity.vector`` from the JOINed embeddings
            # table. The local-embedding path below uses ``SELECT *`` so
            # ``ent.embedding`` comes along for free; the server-side
            # branches project explicit columns and need to opt in.
            query = f"""
                WITH query_vec AS (
                    SELECT {embedding_sql} AS vec
                )
                SELECT
                    ent.id, ent.project_id, ent.file_path, ent.name, ent.qualified_name,
                    ent.entity_type, ent.start_line, ent.end_line, ent.metadata,
                    ent.created_at, ent.updated_at,
                    emb.embedding AS embedding,
                    (emb.embedding {self._distance_op} (SELECT vec FROM query_vec)) AS _distance
                FROM {self._entities_table} ent
                JOIN {self._entity_embeddings_table} emb ON emb.entity_id = ent.id
                WHERE ent.project_id = $2
                  AND emb.project_id = $2
                  AND emb.embedding IS NOT NULL
                  {type_clause}
                ORDER BY emb.embedding {self._distance_op} (SELECT vec FROM query_vec)
                LIMIT $3
            """
        elif self._embedding_strategy == "server_side":
            vector_str = f"[{','.join(str(v) for v in query_vector)}]"
            type_clause = ""
            params = [vector_str, project_id, limit]
            if entity_type:
                type_clause = " AND ent.entity_type = $4"
                params.append(entity_type)

            # See the text-query branch above for why ``emb.embedding AS
            # embedding`` is in the SELECT list.
            query = f"""
                SELECT
                    ent.id, ent.project_id, ent.file_path, ent.name, ent.qualified_name,
                    ent.entity_type, ent.start_line, ent.end_line, ent.metadata,
                    ent.created_at, ent.updated_at,
                    emb.embedding AS embedding,
                    (emb.embedding {self._distance_op} $1::vector) AS _distance
                FROM {self._entities_table} ent
                JOIN {self._entity_embeddings_table} emb ON emb.entity_id = ent.id
                WHERE ent.project_id = $2
                  AND emb.project_id = $2
                  AND emb.embedding IS NOT NULL
                  {type_clause}
                ORDER BY emb.embedding {self._distance_op} $1::vector
                LIMIT $3
            """
        else:
            # Local embedding: query the entities table directly.
            vector_str = f"[{','.join(str(v) for v in query_vector)}]"
            type_clause = ""
            params = [vector_str, project_id, limit]
            if entity_type:
                type_clause = " AND entity_type = $4"
                params.append(entity_type)

            query = f"""
                SELECT *, (embedding {self._distance_op} $1::vector) as _distance
                FROM {self._entities_table}
                WHERE project_id = $2 AND embedding IS NOT NULL {type_clause}
                ORDER BY embedding {self._distance_op} $1::vector
                LIMIT $3
            """

        rows = await self._fetch(query, *params)
        entities: List[GraphEntity] = []
        for row in rows:
            entity = row_to_entity(row)
            entity._distance = row.get("_distance", 1.0)
            entities.append(entity)

        logger.debug(
            "Entity vector search found %d entities for project %s (limit=%d, type=%s)",
            len(entities),
            project_id,
            limit,
            entity_type,
        )
        return entities

    async def count(
        self,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> int:
        """Count chunks matching filters.

        Args:
            filters: Optional filter conditions
            project_id: Optional project scope

        Returns:
            Number of matching chunks
        """
        pid = project_id or self._project_id

        if filters:
            filter_clause, filter_params = self._build_filter_clause(
                filters, param_offset=1
            )
            query = f"""
                SELECT COUNT(*) FROM {self._chunks_table}
                WHERE project_id = $1 {filter_clause}
            """
            params = [pid, *filter_params]
        else:
            query = f"SELECT COUNT(*) FROM {self._chunks_table} WHERE project_id = $1"
            params = [pid]

        result = await self._fetchval(query, *params)
        return int(result or 0)

    async def query_across_projects(
        self,
        table_name: str,
        project_ids: Sequence[str],
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query data across multiple projects.

        Args:
            table_name: Logical table name
            project_ids: List of project IDs
            filters: Optional filter conditions
            limit: Maximum results

        Returns:
            List of matching records as dicts
        """
        if not project_ids:
            return []

        # Map logical table name to actual table
        if table_name in ("document_chunks", "chunks"):
            actual_table = self._chunks_table
        else:
            logger.warning("Unknown table name for vector provider: %s", table_name)
            return []

        # Build filter clause - param_offset=2 because $1=project_ids, $2=limit
        filter_clause, filter_params = self._build_filter_clause(
            filters, param_offset=2
        )

        query = f"""
            SELECT * FROM {actual_table}
            WHERE project_id = ANY($1) {filter_clause}
            LIMIT $2
        """
        params = [list(project_ids), limit, *filter_params]

        rows = await self._fetch(query, *params)
        return [dict(row) for row in rows]

    # =========================================================================
    # Table Management
    # =========================================================================

    async def list_tables(self) -> List[str]:
        """List all tables in the storage.

        Returns:
            List of logical table names
        """
        # Return logical names that this provider manages
        return ["document_chunks", "document_chunks_fts"]

    async def table_exists(self, table_name: str) -> bool:
        """Check if a table exists.

        Args:
            table_name: Logical table name

        Returns:
            True if table exists
        """
        # Map logical to actual table name
        if table_name in ("document_chunks", "chunks"):
            actual_table = self._chunks_table
        elif table_name in ("document_chunks_fts", "chunks_fts"):
            actual_table = self._fts_table
        else:
            return False

        result = await self._conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables
                WHERE table_name = $1
            )
            """,
            actual_table,
        )
        return bool(result)

    # =========================================================================
    # Health Check & Maintenance
    # =========================================================================

    async def health_check(self) -> Dict[str, Any]:
        """Check storage health and include schema version information.

        This method implements NFR-3 by exposing schema version in health checks.
        It queries the connection manager for basic health, adds schema version
        from SchemaVersionTracker, and provides detailed status information.

        Returns:
            Dict with health status information:
            - status: "healthy", "degraded", or "unhealthy"
            - latency_ms: Connection latency in milliseconds
            - schema_version: Current schema version (T4.6)
            - embedding_dimension: Configured embedding dimension
            - index_type: Current index type (hnsw, ivfflat, none)
            - pool_size: Connection pool size
            - error: Error message if unhealthy (optional)

        Example:
            >>> health = await provider.health_check()
            >>> print(f"Status: {health['status']}, version: {health['schema_version']}")
        """
        start_time = time.monotonic()

        try:
            # Get basic connection health from connection manager
            conn_health = await self._conn.health_check()

            # Calculate latency
            latency_ms = (time.monotonic() - start_time) * 1000

            # Get schema version information (T4.6)
            schema_version = None
            index_type = None
            embedding_dimension = None

            try:
                # Import SchemaVersionTracker to query schema info
                from .schema_tracker import SchemaVersionTracker

                tracker = SchemaVersionTracker(self._conn)

                # Get schema info for chunks table
                chunks_table = self._schema_gen.get_table_name(CHUNKS_TABLE)
                schema_info = await tracker.get_schema_info(chunks_table)

                if schema_info:
                    schema_version = schema_info.schema_version
                    embedding_dimension = schema_info.embedding_dimension
                    index_type = schema_info.index_type
                else:
                    # Table not registered yet, use configured values
                    embedding_dimension = self._schema_gen.embedding_dim
                    index_type = "unknown"
                    schema_version = 0

            except Exception as e:
                logger.warning(f"Failed to get schema version: {e}")
                # Continue with basic health check even if schema query fails
                schema_version = None

            # Determine overall health status
            if not conn_health.get("healthy", False):
                status = "unhealthy"
            elif schema_version is None:
                status = "degraded"  # Connection OK but schema info unavailable
            else:
                status = "healthy"

            # Build comprehensive health response
            health_data = {
                "status": status,
                "latency_ms": round(latency_ms, 2),
                "schema_version": schema_version,
                "embedding_dimension": embedding_dimension,
                "index_type": index_type,
                "pool_size": conn_health.get("pool_size"),
                "idle_connections": conn_health.get("idle_connections"),
                "active_connections": conn_health.get("active_connections"),
            }

            # Add error if connection is unhealthy
            if "error" in conn_health:
                health_data["error"] = conn_health["error"]

            return health_data

        except Exception as e:
            logger.error(f"Health check failed: {e}", exc_info=True)
            return {
                "status": "unhealthy",
                "latency_ms": (time.monotonic() - start_time) * 1000,
                "error": str(e),
            }

    async def run_maintenance(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Run storage maintenance operations.

        Placeholder for maintenance operations like VACUUM, REINDEX, etc.
        Full implementation will be added in FR-6 tasks.

        Args:
            project_id: Optional project ID to scope maintenance

        Returns:
            Dict with maintenance results
        """
        return {
            "status": "not_implemented",
            "message": "Maintenance operations not yet implemented",
        }

    # =========================================================================
    # Server-Side Embedding Generation
    # =========================================================================

    # Maximum content length for embedding input (text-embedding-005 has ~2048 token limit)
    EMBEDDING_CONTENT_MAX_CHARS = 8000
    # Batch size for ai.initialize_embeddings() (Vertex AI limit: 250 instances/prediction)
    EMBEDDING_BATCH_SIZE = 250
    # Concurrency for per-row fallback embedding
    EMBEDDING_FALLBACK_CONCURRENCY = 7
    # Batch size for per-row fallback embedding
    EMBEDDING_FALLBACK_BATCH_SIZE = 50

    async def generate_embeddings(self) -> Dict[str, Any]:
        """Generate server-side embeddings using a separate embeddings table.

        Uses a project-safe flow:
        1. Drop HNSW index to avoid maintenance cost during bulk insert
        2. Delete existing embeddings for this project (not TRUNCATE, project-safe)
        3. Populate embeddings table from chunks table for this project
        4. Call bulk embedding via adapter if supported
        5. Fall back to per-row embedding via adapter for any remaining NULL rows
        6. Rebuild HNSW index

        Only runs when embedding_strategy="server_side".

        Returns:
            Dict with embedding generation statistics
        """
        if self._embedding_strategy != "server_side":
            return {"status": "skipped", "reason": "not server_side strategy"}

        # Resolve model
        if self._embedding_model:
            model = self._embedding_model
        elif isinstance(self._adapter, RDSAdapter):
            model = "amazon.titan-embed-text-v2:0"
        else:
            model = "text-embedding-005"

        embeddings_table = self._embeddings_table
        chunks_table = self._chunks_table
        start_time = time.time()

        # Count chunks for this project
        total = await self._fetchval(
            f"SELECT COUNT(*) FROM {chunks_table} WHERE project_id = $1",
            self._project_id,
        )
        total = int(total or 0)
        if total == 0:
            return {"status": "complete", "total": 0, "message": "No chunks to embed"}

        logger.info("Generating server-side embeddings for %d chunks", total)

        # Step 1: Drop HNSW index to avoid maintenance overhead during bulk insert
        index_name = f"idx_{self._schema_gen.prefix}v_chunk_embeddings_embedding"
        await self._execute(f"DROP INDEX IF EXISTS {index_name}")

        # Step 2: Delete existing embeddings for this project (project-safe, not TRUNCATE)
        await self._execute(
            f"DELETE FROM {embeddings_table} WHERE project_id = $1",
            self._project_id,
        )

        # Step 3: Populate embeddings table from chunks table for this project
        await self._execute(
            f"INSERT INTO {embeddings_table} (chunk_id, project_id, content) "
            f"SELECT id, project_id, content FROM {chunks_table} WHERE project_id = $1",
            self._project_id,
        )

        # Step 4: Bulk embedding via adapter
        bulk_embedded = await self._bulk_initialize_embeddings(embeddings_table, model)

        # Step 5: Count remaining NULL embeddings for this project
        remaining = await self._fetchval(
            f"SELECT COUNT(*) FROM {embeddings_table} WHERE project_id = $1 AND embedding IS NULL",
            self._project_id,
        )
        remaining = int(remaining or 0)

        # Step 6: Per-row fallback for remaining NULL rows
        fallback_embedded = 0
        if remaining > 0:
            logger.info(
                "Bulk: %d embedded, %d remaining - using fallback",
                bulk_embedded,
                remaining,
            )
            fallback_embedded = await self._fallback_embed_rows(embeddings_table, model)

        # Step 7: Rebuild HNSW index
        await self._execute(
            f"CREATE INDEX IF NOT EXISTS {index_name} "
            f"ON {embeddings_table} USING hnsw (embedding {self._vector_op_class}) "
            f"WITH (m = 16, ef_construction = 64)"
        )

        # Final stats
        still_null = await self._fetchval(
            f"SELECT COUNT(*) FROM {embeddings_table} WHERE project_id = $1 AND embedding IS NULL",
            self._project_id,
        )
        still_null = int(still_null or 0)
        elapsed = time.time() - start_time
        embedded_total = bulk_embedded + fallback_embedded
        rate = embedded_total / elapsed if elapsed > 0 else 0

        result = {
            "status": "complete",
            "total": total,
            "bulk_embedded": bulk_embedded,
            "fallback_embedded": fallback_embedded,
            "failed": still_null,
            "rate": round(rate, 1),
            "elapsed_seconds": round(elapsed, 1),
        }
        logger.info(
            "Embedding generation complete: %d/%d embedded (%.1f/sec), %d failed",
            embedded_total,
            total,
            rate,
            still_null,
        )
        return result

    async def _bulk_initialize_embeddings(self, table: str, model: str) -> int:
        """Call bulk embedding generation via adapter if supported.

        AlloyDB constraints:
        - ai.initialize_embeddings() / ai.refresh_embeddings() are PROCEDURES (use CALL)
        - They manage their own transactions — cannot be called inside a transaction
        - They only work on persistent tables (not TEMP tables)
        - initialize_embeddings fails if table already has any embeddings; use refresh instead

        Strategy: call CALL directly on the real table, outside any transaction.
        """
        bulk_sql_fn = self._adapter.get_bulk_embedding_sql
        if not bulk_sql_fn("_test", model, "content", "embedding"):
            logger.debug(
                "Adapter %s does not support bulk embedding", self._adapter.backend_type
            )
            return 0

        # Count rows needing embeddings
        null_count = await self._fetchval(
            f"SELECT COUNT(*) FROM {table} WHERE project_id = $1 AND embedding IS NULL",
            self._project_id,
        )
        null_count = int(null_count or 0)
        if null_count == 0:
            logger.info(
                "No NULL embeddings to generate for project %s", self._project_id
            )
            return 0

        # Check if table already has ANY embeddings (determines initialize vs refresh)
        has_existing = await self._fetchval(
            f"SELECT COUNT(*) FROM {table} WHERE embedding IS NOT NULL LIMIT 1"
        )
        has_existing = int(has_existing or 0) > 0

        # Use advisory lock to prevent concurrent embedding contention (#105).
        # ai.initialize_embeddings/refresh_embeddings operate table-wide.
        # Multiple parallel callers cause 1800s+ timeouts.
        lock_key = hash(table) % (2**31)
        try:
            acquired = await self._fetchval("SELECT pg_try_advisory_lock($1)", lock_key)
            if not acquired:
                logger.info(
                    "Bulk embedding lock not acquired for %s — another process is embedding, skipping",
                    table,
                )
                return 0

            if has_existing:
                logger.info(
                    "Bulk embedding: table has existing embeddings, using refresh_embeddings "
                    "for %d NULL rows in project %s",
                    null_count,
                    self._project_id,
                )
                await self._conn.execute(
                    f"CALL ai.refresh_embeddings("
                    f"table_name => '{table}', "
                    f"embedding_column => 'embedding')"
                )
            else:
                bulk_sql = self._adapter.get_bulk_embedding_sql(
                    table, model, "content", "embedding"
                )
                logger.info(
                    "Bulk embedding: fresh table, using initialize_embeddings "
                    "for %d rows in project %s",
                    null_count,
                    self._project_id,
                )
                await self._conn.execute(bulk_sql)

            # Count how many got embedded
            still_null = await self._fetchval(
                f"SELECT COUNT(*) FROM {table} WHERE project_id = $1 AND embedding IS NULL",
                self._project_id,
            )
            still_null = int(still_null or 0)
            embedded = null_count - still_null

            logger.info(
                "Bulk embedding complete: %d/%d embedded for project %s (%d remaining)",
                embedded,
                null_count,
                self._project_id,
                still_null,
            )
            return embedded

        except Exception as e:
            logger.warning("Bulk embedding failed: %s", e, exc_info=True)
            return 0
        finally:
            try:
                await self._conn.execute("SELECT pg_advisory_unlock($1)", lock_key)
            except Exception:
                pass  # Lock released on connection close anyway

    async def _fallback_embed_rows(self, table: str, model: str) -> int:
        """Embed remaining NULL-embedding rows via per-row adapter SQL."""
        rows = await self._fetch(
            f"SELECT chunk_id FROM {table} WHERE project_id = $1 AND embedding IS NULL ORDER BY chunk_id",
            self._project_id,
        )
        if not rows:
            return 0

        all_ids = [r["chunk_id"] for r in rows]
        total = len(all_ids)
        logger.info(
            "Fallback embedding: %d rows to process via %s",
            total,
            self._adapter.backend_type,
        )

        embedded = 0
        batch_size = self.EMBEDDING_FALLBACK_BATCH_SIZE
        batches = [all_ids[i : i + batch_size] for i in range(0, total, batch_size)]

        embedding_sql = self._adapter.get_embedding_sql(
            f"LEFT(content, {self.EMBEDDING_CONTENT_MAX_CHARS})", model
        )

        for batch_idx, batch_ids in enumerate(batches):
            try:
                result = await self._execute(
                    f"UPDATE {table} "
                    f"SET embedding = {embedding_sql} "
                    f"WHERE chunk_id = ANY($1) AND embedding IS NULL",
                    batch_ids,
                )
                count = int(result.split()[-1]) if result else 0
                embedded += count
            except Exception as e:
                logger.warning("Fallback batch %d failed: %s", batch_idx, e)

            if (batch_idx + 1) % 10 == 0 or batch_idx == len(batches) - 1:
                logger.info("Fallback progress: %d/%d embedded", embedded, total)

        return embedded

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _build_filter_clause(
        self,
        filters: "Optional[FilterInput]",
        param_offset: int = 0,
        table_alias: str = "",
    ) -> tuple[str, list]:
        """Build SQL filter clause from a dict or :class:`Filter` AST.

        Delegates to :class:`PostgresFilterAdapter`, which (a) validates
        field names to prevent injection through dict keys, and (b) supports
        the full canonical operator set (EQ/NE/GT/GTE/LT/LTE/LIKE/ILIKE/IN/
        NOT_IN/IS_NULL/IS_NOT_NULL/AND/OR) — the previous inline loop only
        supported equality and was injection-unsafe on field names.

        Args:
            filters: Filter conditions (dict or Filter AST).
            param_offset: Last-used ``$N`` in the surrounding query; this
                method's first placeholder will be ``$(param_offset + 1)``.
            table_alias: Optional table alias prefix for multi-table JOINs.

        Returns:
            Tuple of (filter clause string, parameter values). The clause
            is empty when ``filters`` is None/empty; otherwise it starts
            with a leading space + ``AND`` so it can be appended directly
            to an existing ``WHERE ...`` clause.
        """
        from agent_vault.database.filters import PostgresFilterAdapter

        result = PostgresFilterAdapter(table_alias=table_alias).bind(
            filters, start_index=param_offset + 1
        )
        if result is None:
            return "", []
        return " " + result.where_sql, result.params

    def _row_to_chunk(self, row: Any) -> DocumentChunk:
        """Convert database row to DocumentChunk.

        Args:
            row: asyncpg Record

        Returns:
            DocumentChunk instance
        """
        metadata = row.get("metadata") or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        # Extract vector from pgvector format
        embedding = row.get("embedding")
        if embedding is not None and hasattr(embedding, "tolist"):
            vector = embedding.tolist()
        elif isinstance(embedding, (list, tuple)):
            vector = list(embedding)
        else:
            vector = []

        return DocumentChunk(
            id=row["id"],
            doc_id=row.get("doc_id", row["id"]),
            file_path=row["file_path"],
            project_id=row["project_id"],
            content=row["content"],
            fts_text=row.get("content", ""),  # Use content as FTS text
            vector=vector,
            content_type=row.get("content_type", "PROSE"),
            language=row.get("language", ""),
            line_start=row.get("start_line", -1) or -1,
            line_end=row.get("end_line", -1) or -1,
            chunk_index=row.get("chunk_index", 0),
            metadata=metadata,
        )

    def _row_to_search_result(self, row: Any, source: str) -> SearchResult:
        """Convert database row to SearchResult.

        Args:
            row: asyncpg Record
            source: Result source identifier

        Returns:
            SearchResult instance
        """
        # Calculate normalized score
        if source == "vector":
            # Vector queries select a raw pgvector distance as ``_distance``;
            # convert to a metric-aware similarity in [0, 1] here so the same
            # row shape works for cosine / l2 / dot.
            raw_distance = row.get("_distance")
            if raw_distance is None:
                # Legacy rows may still carry pre-computed ``similarity``.
                score = max(0.0, min(1.0, row.get("similarity", 0.0)))
            else:
                score = distance_to_similarity(
                    float(raw_distance), self._similarity_metric
                )
        elif source == "fts":
            rank = row.get("rank", 0.0)
            # Normalize FTS rank (typically 0-1 but can exceed)
            score = min(1.0, rank)
        else:
            score = 1.0

        # Deserialize JSONB metadata at adapter boundary so downstream
        # code always receives a Python dict (not a JSON string).
        data = dict(row)
        metadata = data.get("metadata")
        if isinstance(metadata, str):
            data["metadata"] = json.loads(metadata)

        return SearchResult(
            id=row["id"],
            data=data,
            score=score,
            source=source,
        )
