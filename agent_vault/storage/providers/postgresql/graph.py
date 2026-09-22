"""PostgreSQL graph storage provider using adjacency list tables.

This module provides a GraphStorageProtocol implementation using PostgreSQL
with entities and relationships stored in separate tables.

Features:
    - Entity storage with vector embeddings (pgvector)
    - Relationship storage with adjacency list model
    - Multi-hop graph traversal via recursive CTEs
    - Project isolation through table prefixes

Requirements:
    - PostgreSQL 12+ (for recursive CTEs)
    - pgvector extension for entity embeddings
    - asyncpg: pip install asyncpg
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from agent_vault.models.graph_entity import GraphEntity
from agent_vault.models.graph_relationship import GraphRelationship
from agent_vault.storage.protocols.graph import GraphStorageProtocol
from agent_vault.storage.providers.postgresql.entity_rows import row_to_entity
from agent_vault.storage.providers.postgresql.adapter import (
    PostgreSQLAdapter,
    DefaultPostgresAdapter,
    AlloyDBAdapter,
    RDSAdapter,
    AzurePostgresAdapter,
)
from agent_vault.storage.errors import SchemaMismatchError
from agent_vault.storage.providers.postgresql.connection import (
    PostgresConnectionManager,
)
from agent_vault.storage.providers.postgresql.schema_tracker import (
    SchemaVersionTracker,
)
from agent_vault.storage.providers.postgresql.schemas import (
    ENTITIES_TABLE,
    ENTITY_EMBEDDINGS_TABLE,
    RELATIONSHIPS_TABLE,
    SchemaGenerator,
)
from agent_vault.storage.similarity import (
    pgvector_distance_operator,
    pgvector_operator_class,
)

if TYPE_CHECKING:
    import asyncpg
    from agent_vault.database.filters import FilterInput
    from agent_vault.storage.capabilities import ProviderCapabilities

logger = logging.getLogger(__name__)


class TransactionError(Exception):
    """Raised when transaction operations fail."""

    pass


class PostgresGraphProvider(GraphStorageProtocol):
    """PostgreSQL implementation of GraphStorageProtocol.

    Uses adjacency list tables for entities and relationships with
    recursive CTEs for graph traversal. Supports server-side embeddings
    via PostgreSQLAdapter.

    Attributes:
        SUPPORTED_ROLES: Roles this provider can fulfill
    """

    SUPPORTED_ROLES = frozenset({"graph"})

    def __init__(
        self,
        connection_manager: PostgresConnectionManager,
        project_id: str,
        *,
        embedding_dim: int = 384,
        embedding_strategy: str = "local",
        embedding_model: Optional[str] = None,
        adapter: Optional[PostgreSQLAdapter] = None,
    ) -> None:
        """Initialize the graph provider.

        Args:
            connection_manager: PostgresConnectionManager instance
            project_id: Project ID for data isolation
            embedding_dim: Vector embedding dimension (default: 384)
            embedding_strategy: "local" or "server_side".
            embedding_model: Server-side embedding model name.
            adapter: Optional cloud-specific adapter.
        """
        self._conn = connection_manager
        self._project_id = project_id
        self._embedding_dim = embedding_dim
        self._embedding_strategy = embedding_strategy
        self._embedding_model = embedding_model
        self._adapter = adapter or DefaultPostgresAdapter()
        self._initialized = False
        self._similarity_metric = connection_manager.similarity_metric
        self._distance_op = pgvector_distance_operator(self._similarity_metric)
        self._vector_op_class = pgvector_operator_class(self._similarity_metric)

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
        self._entities_table = self._schema_gen.get_table_name(ENTITIES_TABLE)
        self._entity_embeddings_table = self._schema_gen.get_table_name(
            ENTITY_EMBEDDINGS_TABLE
        )
        self._relationships_table = self._schema_gen.get_table_name(RELATIONSHIPS_TABLE)

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

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        project_id: str,
    ) -> "PostgresGraphProvider":
        """Create provider from configuration dict."""
        from agent_vault.storage.config import BackendConfig

        # 1. Resolve Adapter
        backend_type = config.get("type", "postgresql")
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

        # 2. Build connection manager
        if backend_type == "alloydb":
            from agent_vault.storage.providers.alloydb import AlloyDBConnectionManager

            manager = AlloyDBConnectionManager.from_config(config)
        else:
            valid_fields = set(BackendConfig.model_fields.keys())
            # Filter config to only valid BackendConfig fields
            backend_config_data = {
                k: v for k, v in config.items() if k in valid_fields and k != "type"
            }

            # Build DSN if missing and we have cloud params
            if not backend_config_data.get("connection_string"):
                if backend_type == "rds":
                    from .vector import PostgresVectorProvider

                    backend_config_data["connection_string"] = (
                        PostgresVectorProvider._build_rds_dsn(config)
                    )
                elif backend_type in ("alloydb", "cloudsql"):
                    from .vector import PostgresVectorProvider

                    backend_config_data["connection_string"] = (
                        PostgresVectorProvider._build_dsn_from_config(config)
                    )

            backend_config = BackendConfig(**backend_config_data, type=backend_type)
            manager = PostgresConnectionManager(
                connection_string=backend_config.connection_string,
                table_prefix=config.get("table_prefix", "agv_"),
                pool_size=backend_config.pool_size,
                max_overflow=backend_config.max_overflow,
            )

        # 3. Resolve embedding strategy and dimensions
        # Auto-detect server_side for AlloyDB/CloudSQL when not explicitly set
        default_strategy = (
            "server_side" if backend_type in ("alloydb", "cloudsql") else "local"
        )
        embedding_strategy = config.get("embedding_strategy", default_strategy)
        embedding_model = config.get("embedding_model")

        # Default dims based on provider defaults if not specified
        default_dim = 384
        if embedding_strategy == "server_side":
            if backend_type == "rds":
                default_dim = 1024
            elif backend_type == "alloydb":
                default_dim = 768

        embedding_dim = config.get("embedding_dim", default_dim)

        return cls(
            manager,
            project_id,
            embedding_dim=embedding_dim,
            embedding_strategy=embedding_strategy,
            embedding_model=embedding_model,
            adapter=adapter,
        )

    async def initialize(self) -> None:
        """Initialize the storage backend."""
        if self._initialized:
            return

        await self._conn.initialize()

        # Ensure required extensions are installed via adapter.
        # Strategy-aware: LOCAL deployments don't ensure cloud-specific
        # ML extensions (``aws_ml``/``azure_ai``/``google_ml_integration``)
        # they wouldn't be able to install anyway.
        for ext in self._adapter.required_extensions(self._embedding_strategy):
            await self._conn.ensure_extension(ext)

        # Adapter-specific initialization (e.g. creating helper functions)
        if self._embedding_strategy == "server_side":
            if isinstance(self._adapter, RDSAdapter):
                model = self._embedding_model or "amazon.titan-embed-text-v2:0"
                await self._adapter.create_helper_function(self._conn, model)
            else:
                await self._adapter.on_initialize(self._conn)

        # Create tables
        for stmt in self._schema_gen.get_create_statements("graph"):
            await self._execute(stmt)

        self._initialized = True
        logger.info(
            "PostgresGraphProvider initialized for project: %s (backend: %s)",
            self._project_id,
            self._adapter.backend_type,
        )

    def set_transaction_connection(self, connection: asyncpg.Connection) -> None:
        """Set the transaction connection for coordinated operations.

        This method is called by TransactionCoordinator to inject a shared
        connection for atomic multi-provider operations (AC-4, AC-5).

        Args:
            connection: Shared database connection for the transaction

        Raises:
            TransactionError: If already in a transaction
        """
        if self._txn_connection is not None:
            raise TransactionError(
                "Provider already has a transaction connection. "
                "Cannot nest transactions."
            )
        self._txn_connection = connection
        logger.debug("Transaction connection injected into GraphProvider")

    def clear_transaction_connection(self) -> None:
        """Clear the transaction connection after commit/rollback.

        This method is called by TransactionCoordinator after the transaction
        completes (either commit or rollback).
        """
        self._txn_connection = None
        logger.debug("Transaction connection cleared from GraphProvider")

    @property
    def in_transaction(self) -> bool:
        """Check if provider is currently in a transaction.

        Returns:
            True if transaction connection is set, False otherwise
        """
        return self._txn_connection is not None

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
    ) -> "PostgresGraphProvider":
        """Create provider from configuration dict.

        Supports both direct connection_string and GCP proxy params.

        Args:
            config: Configuration with connection_string or GCP params
            project_id: Project ID for data isolation

        Returns:
            Configured PostgresGraphProvider instance
        """
        # Build connection string from GCP params if not provided directly
        resolved_config = dict(config)
        if not resolved_config.get("connection_string"):
            from agent_vault.storage.providers.postgresql.vector import (
                PostgresVectorProvider,
            )

            resolved_config["connection_string"] = (
                PostgresVectorProvider._build_dsn_from_config(config)
            )

        manager = PostgresConnectionManager.from_config(
            resolved_config,
            table_prefix=config.get("table_prefix", "agv_"),
        )

        backend_type = config.get("type", "postgresql")
        default_strategy = (
            "server_side" if backend_type in ("alloydb", "cloudsql") else "local"
        )
        embedding_strategy = config.get("embedding_strategy", default_strategy)
        embedding_dim = config.get(
            "embedding_dim", 768 if embedding_strategy == "server_side" else 384
        )

        # Resolve adapter based on backend type
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

        return cls(
            manager,
            project_id,
            embedding_dim=embedding_dim,
            embedding_strategy=embedding_strategy,
            embedding_model=config.get("embedding_model"),
            adapter=adapter,
        )

    # =========================================================================
    # Lifecycle Methods
    # =========================================================================

    async def initialize(self) -> None:
        """Initialize the storage backend.

        Creates tables and indexes if they don't exist.
        Idempotent - safe to call multiple times.
        """
        if self._initialized:
            return

        await self._conn.initialize()

        # Ensure pgvector extension is installed
        await self._conn.ensure_extension("vector")

        # Server-side embedding requires google_ml_integration extension
        if self._embedding_strategy == "server_side":
            await self._conn.ensure_extension("google_ml_integration")

        # Dimension-mismatch detection: if the entities table (or its server-side
        # sibling) already exists with a different vector dim, fail fast with a
        # clear error rather than surfacing at upsert time as an opaque pgvector
        # type error. Embedding dim is immutable post-creation — migrating
        # requires dropping and recreating the table.
        tracker = SchemaVersionTracker(self._conn)
        for table_name in self._dim_checked_tables():
            mismatch = await tracker.detect_dimension_mismatch(
                table_name, self._embedding_dim
            )
            if mismatch:
                logger.error(str(mismatch))
                raise SchemaMismatchError(str(mismatch))

        # Create entities table and its indexes
        await self._execute(self._schema_gen.generate_create_table(ENTITIES_TABLE))
        for idx_sql in self._schema_gen.generate_indexes(ENTITIES_TABLE):
            await self._execute(idx_sql)

        # Create relationships table and its indexes
        await self._execute(self._schema_gen.generate_create_table(RELATIONSHIPS_TABLE))
        for idx_sql in self._schema_gen.generate_indexes(RELATIONSHIPS_TABLE):
            await self._execute(idx_sql)

        # Create separate entity embeddings table for server-side embedding strategy
        if self._embedding_strategy == "server_side":
            embeddings_ddl = self._schema_gen.generate_create_table(
                ENTITY_EMBEDDINGS_TABLE
            )
            await self._execute(embeddings_ddl)
            for idx_sql in self._schema_gen.generate_indexes(ENTITY_EMBEDDINGS_TABLE):
                await self._execute(idx_sql)

        self._initialized = True
        logger.info(
            "PostgresGraphProvider initialized for project: %s", self._project_id
        )

    def _dim_checked_tables(self) -> List[str]:
        """Tables with an ``embedding vector(N)`` column to validate at init."""
        tables = [self._entities_table]
        if self._embedding_strategy == "server_side":
            tables.append(self._entity_embeddings_table)
        return tables

    async def close(self) -> None:
        """Close the storage backend connection.

        Releases resources. Safe to call multiple times.
        """
        # Connection manager is shared, don't close it here
        self._initialized = False
        logger.debug("PostgresGraphProvider closed for project: %s", self._project_id)

    # =========================================================================
    # Entity CRUD Operations
    # =========================================================================

    # Default batch size for bulk operations (reduces network round-trips)
    _BATCH_SIZE = 1000

    async def upsert_entities(
        self,
        entities: Sequence[GraphEntity],
        project_id: str,
        batch_size: Optional[int] = None,
    ) -> int:
        """Insert or update graph entities using batch operations.

        Args:
            entities: Sequence of GraphEntity objects
            project_id: Project scope for isolation
            batch_size: Number of entities per batch (default: 1000)

        Returns:
            Number of entities upserted
        """
        if not entities:
            return 0

        batch_size = batch_size or self._BATCH_SIZE

        # Helper to get attribute from dict or object
        def _get_attr(obj, attr, default=None):
            if isinstance(obj, dict):
                return obj.get(attr, default)
            return getattr(obj, attr, default)

        # Prepare all parameters upfront for batch insert
        server_side = self._embedding_strategy == "server_side"
        params_list = []
        for entity in entities:
            base_params = (
                _get_attr(entity, "id"),
                project_id,
                _get_attr(entity, "file_path"),
                _get_attr(entity, "name"),
                f"{_get_attr(entity, 'file_path')}::{_get_attr(entity, 'name')}",  # qualified_name
                _get_attr(entity, "type"),
                _get_attr(entity, "line_start", -1)
                if _get_attr(entity, "line_start", -1) >= 0
                else None,
                _get_attr(entity, "line_end", -1)
                if _get_attr(entity, "line_end", -1) >= 0
                else None,
            )

            metadata_json = json.dumps(
                {
                    "pagerank": _get_attr(entity, "pagerank"),
                    "betweenness": _get_attr(entity, "betweenness"),
                    "community_id": _get_attr(entity, "community_id"),
                    "doc_id": _get_attr(entity, "doc_id"),
                }
            )

            if server_side:
                params_list.append((*base_params, metadata_json))
            else:
                vector = _get_attr(entity, "vector", [])
                vector_str = f"[{','.join(str(v) for v in vector)}]" if vector else None
                params_list.append((*base_params, vector_str, metadata_json))

        # Execute in batches within a single transaction
        if server_side:
            query = f"""
                INSERT INTO {self._entities_table} (
                    id, project_id, file_path, name, qualified_name,
                    entity_type, start_line, end_line, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (project_id, qualified_name)
                DO UPDATE SET
                    file_path = EXCLUDED.file_path,
                    name = EXCLUDED.name,
                    entity_type = EXCLUDED.entity_type,
                    start_line = EXCLUDED.start_line,
                    end_line = EXCLUDED.end_line,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
            """
        else:
            query = f"""
                INSERT INTO {self._entities_table} (
                    id, project_id, file_path, name, qualified_name,
                    entity_type, start_line, end_line, embedding, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::vector, $10)
                ON CONFLICT (project_id, qualified_name)
                DO UPDATE SET
                    file_path = EXCLUDED.file_path,
                    name = EXCLUDED.name,
                    entity_type = EXCLUDED.entity_type,
                    start_line = EXCLUDED.start_line,
                    end_line = EXCLUDED.end_line,
                    embedding = EXCLUDED.embedding,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
            """

        count = 0
        async with self._conn.transaction() as conn:
            # Process in batches to avoid memory issues with very large datasets
            for i in range(0, len(params_list), batch_size):
                batch = params_list[i : i + batch_size]
                await conn.executemany(query, batch)
                count += len(batch)

        logger.debug(
            "Upserted %d entities for project %s (batch_size=%d)",
            count,
            project_id,
            batch_size,
        )
        return count

    async def get_entity(
        self,
        entity_id: str,
        project_id: str,
    ) -> Optional[GraphEntity]:
        """Get a single entity by ID.

        Args:
            entity_id: Unique entity identifier
            project_id: Project scope for isolation

        Returns:
            GraphEntity if found, None otherwise
        """
        row = await self._fetchrow(
            f"""
            SELECT * FROM {self._entities_table}
            WHERE project_id = $1 AND id = $2
            """,
            project_id,
            entity_id,
        )
        return self._row_to_entity(row) if row else None

    async def get_entities_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> List[GraphEntity]:
        """Get all entities from a specific file.

        Args:
            file_path: Path to the source file
            project_id: Project scope for isolation

        Returns:
            List of GraphEntity objects
        """
        rows = await self._fetch(
            f"""
            SELECT * FROM {self._entities_table}
            WHERE project_id = $1 AND file_path = $2
            ORDER BY start_line
            """,
            project_id,
            file_path,
        )
        return [self._row_to_entity(row) for row in rows]

    async def get_entities_by_type(
        self,
        entity_type: str,
        project_id: str,
        limit: int = 100,
    ) -> List[GraphEntity]:
        """Get entities by type.

        Args:
            entity_type: Type of entities to retrieve
            project_id: Project scope for isolation
            limit: Maximum number of results

        Returns:
            List of GraphEntity objects
        """
        rows = await self._fetch(
            f"""
            SELECT * FROM {self._entities_table}
            WHERE project_id = $1 AND entity_type = $2
            LIMIT $3
            """,
            project_id,
            entity_type,
            limit,
        )
        return [self._row_to_entity(row) for row in rows]

    async def delete_entities_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> int:
        """Delete all entities from a specific file.

        Args:
            file_path: Path to the source file
            project_id: Project scope for isolation

        Returns:
            Number of entities deleted
        """
        result = await self._execute(
            f"""
            DELETE FROM {self._entities_table}
            WHERE project_id = $1 AND file_path = $2
            """,
            project_id,
            file_path,
        )
        count = int(result.split()[-1]) if result else 0
        logger.debug("Deleted %d entities from %s", count, file_path)
        return count

    async def delete_entities_by_ids(
        self,
        entity_ids: List[str],
        project_id: str,
    ) -> int:
        """Delete entities by their IDs.

        Args:
            entity_ids: List of entity IDs to delete
            project_id: Project scope for isolation

        Returns:
            Number of entities deleted
        """
        if not entity_ids:
            return 0

        result = await self._execute(
            f"""
            DELETE FROM {self._entities_table}
            WHERE project_id = $1 AND id = ANY($2)
            """,
            project_id,
            entity_ids,
        )
        count = int(result.split()[-1]) if result else 0
        logger.debug("Deleted %d entities by ID", count)
        return count

    async def query_entities(
        self,
        filters: Dict[str, Any],
        project_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GraphEntity]:
        """Query entities with filters.

        Args:
            filters: Filter conditions
            project_id: Project scope for isolation
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of matching GraphEntity objects
        """
        filter_clause, filter_params = self._build_filter_clause(
            filters, param_offset=1
        )

        # Dynamically compute LIMIT/OFFSET param numbers after filter params
        limit_param = len(filter_params) + 2  # $1 is project_id, filters start at $2
        offset_param = len(filter_params) + 3

        query = f"""
            SELECT * FROM {self._entities_table}
            WHERE project_id = $1 {filter_clause}
            LIMIT ${limit_param} OFFSET ${offset_param}
        """
        params = [project_id, *filter_params, limit, offset]

        rows = await self._fetch(query, *params)
        return [self._row_to_entity(row) for row in rows]

    async def count_entities(
        self,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> int:
        """Count entities matching filters.

        Args:
            filters: Optional filter conditions
            project_id: Optional project scope

        Returns:
            Number of matching entities
        """
        pid = project_id or self._project_id

        if filters:
            filter_clause, filter_params = self._build_filter_clause(
                filters, param_offset=1
            )
            query = f"""
                SELECT COUNT(*) FROM {self._entities_table}
                WHERE project_id = $1 {filter_clause}
            """
            params = [pid, *filter_params]
        else:
            query = f"SELECT COUNT(*) FROM {self._entities_table} WHERE project_id = $1"
            params = [pid]

        result = await self._fetchval(query, *params)
        return int(result or 0)

    # =========================================================================
    # Relationship CRUD Operations
    # =========================================================================

    async def upsert_relationships(
        self,
        relationships: Sequence[GraphRelationship],
        project_id: str,
        batch_size: Optional[int] = None,
    ) -> int:
        """Insert or update graph relationships using batch operations.

        Args:
            relationships: Sequence of GraphRelationship objects
            project_id: Project scope for isolation
            batch_size: Number of relationships per batch (default: 1000)

        Returns:
            Number of relationships upserted
        """
        if not relationships:
            return 0

        batch_size = batch_size or self._BATCH_SIZE

        # Prepare all parameters upfront for batch insert
        params_list = [
            (
                rel.id,
                project_id,
                "",  # file_path not in GraphRelationship model
                rel.source_id,
                rel.target_id,
                rel.type,
                1.0,  # Default weight
                rel.metadata or "{}",
            )
            for rel in relationships
        ]

        query = f"""
            INSERT INTO {self._relationships_table} (
                id, project_id, file_path, source_id, target_id,
                relationship_type, weight, metadata
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (project_id, source_id, target_id, relationship_type)
            DO UPDATE SET
                file_path = EXCLUDED.file_path,
                weight = EXCLUDED.weight,
                metadata = EXCLUDED.metadata
        """

        count = 0
        async with self._conn.transaction() as conn:
            # Process in batches to avoid memory issues with very large datasets
            for i in range(0, len(params_list), batch_size):
                batch = params_list[i : i + batch_size]
                await conn.executemany(query, batch)
                count += len(batch)

        logger.debug(
            "Upserted %d relationships for project %s (batch_size=%d)",
            count,
            project_id,
            batch_size,
        )
        return count

    async def get_relationships_by_entity(
        self,
        entity_id: str,
        direction: str = "both",
        relationship_types: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> List[GraphRelationship]:
        """Get relationships for an entity.

        Args:
            entity_id: Entity to get relationships for
            direction: "outgoing", "incoming", or "both"
            relationship_types: Optional filter by relationship types
            project_id: Optional project scope

        Returns:
            List of GraphRelationship objects
        """
        pid = project_id or self._project_id
        type_clause = ""
        params: list = [pid, entity_id]

        if relationship_types:
            type_clause = f"AND relationship_type = ANY(${len(params) + 1})"
            params.append(relationship_types)

        if direction == "outgoing":
            where = "source_id = $2"
        elif direction == "incoming":
            where = "target_id = $2"
        else:  # both
            where = "(source_id = $2 OR target_id = $2)"

        query = f"""
            SELECT * FROM {self._relationships_table}
            WHERE project_id = $1 AND {where} {type_clause}
        """

        rows = await self._fetch(query, *params)
        return [self._row_to_relationship(row) for row in rows]

    async def count_relationships_by_type(
        self,
        project_id: str,
    ) -> Dict[str, int]:
        """Count relationships grouped by relationship type.

        Args:
            project_id: Project scope for isolation

        Returns:
            Dictionary mapping relationship type to count
        """
        query = f"""
            SELECT relationship_type, COUNT(*) as count
            FROM {self._relationships_table}
            WHERE project_id = $1
            GROUP BY relationship_type
            ORDER BY count DESC
        """
        rows = await self._fetch(query, project_id)
        return {row["relationship_type"]: int(row["count"]) for row in rows}

    async def delete_relationships_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> int:
        """Delete all relationships from a specific file.

        Args:
            file_path: Path to the source file
            project_id: Project scope for isolation

        Returns:
            Number of relationships deleted
        """
        result = await self._execute(
            f"""
            DELETE FROM {self._relationships_table}
            WHERE project_id = $1 AND file_path = $2
            """,
            project_id,
            file_path,
        )
        count = int(result.split()[-1]) if result else 0
        logger.debug("Deleted %d relationships from %s", count, file_path)
        return count

    async def delete_relationships_by_entity(
        self,
        entity_id: str,
        project_id: str,
    ) -> int:
        """Delete all relationships for an entity.

        Args:
            entity_id: Entity to delete relationships for
            project_id: Project scope for isolation

        Returns:
            Number of relationships deleted
        """
        result = await self._execute(
            f"""
            DELETE FROM {self._relationships_table}
            WHERE project_id = $1 AND (source_id = $2 OR target_id = $2)
            """,
            project_id,
            entity_id,
        )
        count = int(result.split()[-1]) if result else 0
        logger.debug("Deleted %d relationships for entity %s", count, entity_id)
        return count

    async def delete_relationships_by_ids(
        self,
        relationship_ids: Sequence[str],
        project_id: str,
    ) -> int:
        """Delete relationships by their IDs.

        Args:
            relationship_ids: List of relationship IDs to delete
            project_id: Project scope for isolation

        Returns:
            Number of relationships deleted
        """
        if not relationship_ids:
            return 0

        result = await self._execute(
            f"""
            DELETE FROM {self._relationships_table}
            WHERE project_id = $1 AND id = ANY($2)
            """,
            project_id,
            list(relationship_ids),
        )
        count = int(result.split()[-1]) if result else 0
        logger.debug("Deleted %d relationships by ID", count)
        return count

    async def query_relationships(
        self,
        filters: "FilterInput",
        project_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GraphRelationship]:
        """Query relationships with filters.

        Both dict and AST inputs flow through ``_build_filter_clause`` with
        :attr:`_RELATIONSHIP_COLUMN_MAP`, so an ``eq("type", ...)`` in
        either shape is rewritten to ``relationship_type`` uniformly. The
        prior code only pre-mapped dict keys, which meant an AST caller
        could silently hit ``entity_type`` (via the default entity map)
        and return empty results.

        Args:
            filters: Filter conditions (dict or Filter AST).
            project_id: Project scope for isolation.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            List of matching GraphRelationship objects.
        """
        filter_clause, filter_params = self._build_filter_clause(
            filters,
            param_offset=1,
            field_map=self._RELATIONSHIP_COLUMN_MAP,
        )

        # Dynamically compute LIMIT/OFFSET param numbers after filter params
        limit_param = len(filter_params) + 2  # $1 is project_id, filters start at $2
        offset_param = len(filter_params) + 3

        query = f"""
            SELECT * FROM {self._relationships_table}
            WHERE project_id = $1 {filter_clause}
            LIMIT ${limit_param} OFFSET ${offset_param}
        """
        params = [project_id, *filter_params, limit, offset]

        rows = await self._fetch(query, *params)
        return [self._row_to_relationship(row) for row in rows]

    # =========================================================================
    # Graph Traversal
    # =========================================================================

    async def get_neighbors(
        self,
        entity_id: str,
        direction: str = "both",
        depth: int = 1,
        relationship_types: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> List[GraphEntity]:
        """Get neighboring entities.

        Args:
            entity_id: Starting entity ID
            direction: "outgoing", "incoming", or "both"
            depth: How many hops to traverse
            relationship_types: Optional filter by relationship types
            project_id: Optional project scope

        Returns:
            List of neighboring GraphEntity objects
        """
        pid = project_id or self._project_id

        # Build direction clause
        if direction == "outgoing":
            join_condition = "r.source_id = visited.entity_id"
            next_entity = "r.target_id"
        elif direction == "incoming":
            join_condition = "r.target_id = visited.entity_id"
            next_entity = "r.source_id"
        else:  # both
            join_condition = (
                "(r.source_id = visited.entity_id OR r.target_id = visited.entity_id)"
            )
            next_entity = "CASE WHEN r.source_id = visited.entity_id THEN r.target_id ELSE r.source_id END"

        # Build type filter
        type_filter = ""
        params: list = [pid, entity_id, depth]
        if relationship_types:
            type_filter = f"AND r.relationship_type = ANY(${len(params) + 1})"
            params.append(relationship_types)

        query = f"""
            WITH RECURSIVE traversal AS (
                -- Base case: start entity
                SELECT id as entity_id, 0 as depth
                FROM {self._entities_table}
                WHERE project_id = $1 AND id = $2

                UNION

                -- Recursive case: follow relationships
                SELECT DISTINCT {next_entity} as entity_id, visited.depth + 1
                FROM traversal visited
                JOIN {self._relationships_table} r ON {join_condition} AND r.project_id = $1 {type_filter}
                WHERE visited.depth < $3
            )
            SELECT e.* FROM {self._entities_table} e
            JOIN (SELECT DISTINCT entity_id FROM traversal WHERE depth > 0) t ON e.id = t.entity_id
            WHERE e.project_id = $1
        """

        rows = await self._fetch(query, *params)
        return [self._row_to_entity(row) for row in rows]

    async def traverse(
        self,
        start_entity_id: str,
        max_depth: int = 2,
        relationship_types: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Traverse the graph from a starting entity.

        Args:
            start_entity_id: Starting entity ID
            max_depth: Maximum traversal depth
            relationship_types: Optional filter by relationship types
            project_id: Optional project scope

        Returns:
            Dict with entities, relationships, and metadata
        """
        pid = project_id or self._project_id

        # Get start entity
        start_entity = await self.get_entity(start_entity_id, pid)
        if not start_entity:
            return {
                "entities": [],
                "relationships": [],
                "start_entity": None,
                "depth_reached": 0,
            }

        # Get all neighbors at each depth level
        all_entities: Dict[str, GraphEntity] = {start_entity_id: start_entity}
        all_relationships: List[GraphRelationship] = []
        current_ids = {start_entity_id}
        depth_reached = 0

        for depth in range(max_depth):
            # Get relationships from current frontier
            for entity_id in current_ids:
                rels = await self.get_relationships_by_entity(
                    entity_id,
                    direction="both",
                    relationship_types=relationship_types,
                    project_id=pid,
                )
                for rel in rels:
                    if rel.id not in [r.id for r in all_relationships]:
                        all_relationships.append(rel)

            # Get next frontier
            next_ids: set = set()
            for rel in all_relationships:
                for eid in (rel.source_id, rel.target_id):
                    if eid not in all_entities:
                        next_ids.add(eid)

            if not next_ids:
                break

            # Fetch new entities
            for eid in next_ids:
                entity = await self.get_entity(eid, pid)
                if entity:
                    all_entities[eid] = entity

            current_ids = next_ids
            depth_reached = depth + 1

        return {
            "entities": list(all_entities.values()),
            "relationships": all_relationships,
            "start_entity": start_entity,
            "depth_reached": depth_reached,
        }

    # ``entity_vector_search`` moved to :class:`PostgresVectorProvider` —
    # the embedding column is a vector-space concern even though the rest
    # of the entity schema is graph-owned. See ``vector.py`` for the impl.

    # =========================================================================
    # Server-Side Embedding Generation
    # =========================================================================

    # Batch size for bulk embedding if supported
    EMBEDDING_BATCH_SIZE = 250
    # Batch size for per-entity fallback embedding
    EMBEDDING_FALLBACK_BATCH_SIZE = 50

    async def generate_embeddings(self) -> Dict[str, Any]:
        """Generate server-side embeddings using a separate entity embeddings table.

        Uses a project-safe flow:
        1. Drop HNSW index to avoid maintenance cost during bulk insert
        2. DELETE FROM entity_embeddings WHERE project_id = $1 (project-safe)
        3. INSERT INTO entity_embeddings SELECT id, project_id, content FROM entities
        4. Call bulk embedding via adapter if supported
        5. Fallback per-row embedding via adapter for remaining NULLs
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

        embeddings_table = self._entity_embeddings_table
        entities_table = self._entities_table
        start_time = time.time()

        # Count entities for this project
        total = await self._fetchval(
            f"SELECT COUNT(*) FROM {entities_table} WHERE project_id = $1",
            self._project_id,
        )
        total = int(total or 0)
        if total == 0:
            return {"status": "complete", "total": 0, "message": "No entities to embed"}

        logger.info("Generating server-side embeddings for %d entities", total)

        # Step 1: Drop HNSW index
        index_name = f"idx_{self._schema_gen.prefix}g_entity_embeddings_embedding"
        await self._execute(f"DROP INDEX IF EXISTS {index_name}")

        # Step 2: Delete existing embeddings for this project
        await self._execute(
            f"DELETE FROM {embeddings_table} WHERE project_id = $1",
            self._project_id,
        )

        # Step 3: Populate embeddings table from entities table
        await self._execute(
            f"INSERT INTO {embeddings_table} (entity_id, project_id, content) "
            f"SELECT id, project_id, name || ' ' || qualified_name "
            f"FROM {entities_table} WHERE project_id = $1",
            self._project_id,
        )

        # Step 4: Bulk embedding via adapter
        bulk_embedded = await self._bulk_initialize_embeddings(embeddings_table, model)

        # Step 5: Count remaining NULL embeddings
        remaining = await self._fetchval(
            f"SELECT COUNT(*) FROM {embeddings_table} WHERE project_id = $1 AND embedding IS NULL",
            self._project_id,
        )
        remaining = int(remaining or 0)

        # Step 6: Per-row fallback
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
        return result

    async def _bulk_initialize_embeddings(self, table: str, model: str) -> int:
        """Call bulk embedding generation via adapter if supported.

        AlloyDB: uses CALL (procedure, not function), no temp tables,
        initialize_embeddings for fresh tables, refresh_embeddings for existing.
        """
        bulk_sql = self._adapter.get_bulk_embedding_sql(
            table, model, "content", "embedding"
        )
        if not bulk_sql:
            return 0

        before_null = await self._fetchval(
            f"SELECT COUNT(*) FROM {table} WHERE embedding IS NULL"
        )
        before_null = int(before_null or 0)
        if before_null == 0:
            return 0

        has_existing = await self._fetchval(
            f"SELECT COUNT(*) FROM {table} WHERE embedding IS NOT NULL LIMIT 1"
        )
        has_existing = int(has_existing or 0) > 0

        # Use advisory lock to prevent concurrent embedding contention (#105).
        # ai.initialize_embeddings/refresh_embeddings operate table-wide, not
        # per-project. Multiple parallel callers cause 1800s+ timeouts.
        # Lock key is a hash of the table name — same table = same lock.
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
                    "Entity bulk embedding: using refresh_embeddings (%d NULL)",
                    before_null,
                )
                await self._conn.execute(
                    f"CALL ai.refresh_embeddings("
                    f"table_name => '{table}', "
                    f"embedding_column => 'embedding')"
                )
            else:
                logger.info(
                    "Entity bulk embedding: using initialize_embeddings (%d rows)",
                    before_null,
                )
                await self._conn.execute(bulk_sql)
        except Exception as e:
            logger.warning("Bulk entity embedding failed: %s", e, exc_info=True)
            return 0
        finally:
            try:
                await self._conn.execute("SELECT pg_advisory_unlock($1)", lock_key)
            except Exception:
                pass  # Lock released on connection close anyway

        after_null = await self._fetchval(
            f"SELECT COUNT(*) FROM {table} WHERE embedding IS NULL"
        )
        after_null = int(after_null or 0)

        return before_null - after_null

    async def _fallback_embed_rows(self, table: str, model: str) -> int:
        """Embed remaining NULL-embedding rows via per-row adapter SQL."""
        rows = await self._fetch(
            f"SELECT entity_id FROM {table} WHERE project_id = $1 AND embedding IS NULL ORDER BY entity_id",
            self._project_id,
        )
        if not rows:
            return 0

        all_ids = [r["entity_id"] for r in rows]
        total = len(all_ids)
        logger.info(
            "Fallback entity embedding: %d rows via %s",
            total,
            self._adapter.backend_type,
        )

        embedded = 0
        batch_size = self.EMBEDDING_FALLBACK_BATCH_SIZE
        batches = [all_ids[i : i + batch_size] for i in range(0, total, batch_size)]

        embedding_sql = self._adapter.get_embedding_sql("content", model)

        for batch_idx, batch_ids in enumerate(batches):
            try:
                result = await self._execute(
                    f"UPDATE {table} "
                    f"SET embedding = {embedding_sql} "
                    f"WHERE entity_id = ANY($1) AND embedding IS NULL",
                    batch_ids,
                )
                count = int(result.split()[-1]) if result else 0
                embedded += count
            except Exception as e:
                logger.warning("Entity fallback batch %d failed: %s", batch_idx, e)

        return embedded

    # =========================================================================
    # Private Helpers
    # =========================================================================

    # Model-field → DB-column maps per table. Graph entities use
    # ``entity_type``; relationships use ``relationship_type``. Callers
    # pass the right one via ``_build_filter_clause(..., field_map=...)``
    # because a single shared map would silently mis-route AST filters at
    # query_relationships (an AST ``eq("type", ...)`` would otherwise be
    # rewritten to ``entity_type`` — a column that doesn't exist on the
    # relationships table).
    _ENTITY_COLUMN_MAP = {"type": "entity_type"}
    _RELATIONSHIP_COLUMN_MAP = {"type": "relationship_type"}

    def _build_filter_clause(
        self,
        filters: "Optional[FilterInput]",
        param_offset: int = 0,
        *,
        field_map: Optional[Dict[str, str]] = None,
    ) -> tuple[str, list]:
        """Build SQL filter clause from filter dict or Filter AST.

        Delegates to :class:`PostgresFilterAdapter`. Supports the full
        canonical operator set with validated, parameterized SQL.

        Args:
            filters: Filter conditions (dict or Filter AST).
            param_offset: Last-used ``$N`` — next placeholder is
                ``$(param_offset + 1)``.
            field_map: Model-field → DB-column rename map. Defaults to
                :attr:`_ENTITY_COLUMN_MAP` so entity-table callers don't
                have to spell it out. Relationship-table callers pass
                :attr:`_RELATIONSHIP_COLUMN_MAP`.

        Returns:
            Tuple of (filter clause string, parameter values). Clause is
            empty when no filter applies; otherwise starts with a leading
            space + ``AND`` so it appends cleanly after a ``WHERE`` clause.
        """
        from agent_vault.database.filters import PostgresFilterAdapter

        effective_map = (
            field_map if field_map is not None else self._ENTITY_COLUMN_MAP
        )
        result = PostgresFilterAdapter(field_map=effective_map).bind(
            filters, start_index=param_offset + 1
        )
        if result is None:
            return "", []
        return " " + result.where_sql, result.params

    # ``_translate_filter_ast`` has been subsumed by
    # :class:`agent_vault.database.filters.PostgresFilterAdapter` — see
    # ``_build_filter_clause`` above for the delegation.

    def _row_to_entity(self, row: Any) -> GraphEntity:
        """Convert a row from the entities table into a GraphEntity.

        Delegates to the shared :func:`row_to_entity` helper so the vector
        provider (which also reads this table for ``entity_vector_search``)
        uses the same hydration logic.
        """
        return row_to_entity(row)

    def _row_to_relationship(self, row: Any) -> GraphRelationship:
        """Convert database row to GraphRelationship.

        Args:
            row: asyncpg Record

        Returns:
            GraphRelationship instance
        """
        # Ensure metadata is a JSON string for GraphRelationship model.
        # asyncpg may return JSONB as a Python dict; serialize it back.
        metadata = row.get("metadata")
        if isinstance(metadata, dict):
            metadata = json.dumps(metadata)

        # Use from_db_dict which handles column name mapping
        # PostgreSQL uses 'relationship_type', model uses 'type'
        return GraphRelationship.from_db_dict(
            {
                "id": row["id"],
                "source_id": row["source_id"],
                "target_id": row["target_id"],
                "relationship_type": row[
                    "relationship_type"
                ],  # Will be mapped to 'type'
                "project_id": row["project_id"],
                "vector": [],  # Relationships don't have vectors in this schema
                "metadata": metadata,
            },
            backend="postgresql",
        )
