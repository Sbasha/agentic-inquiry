"""PostgreSQL storage providers for agent_vault.

This package provides PostgreSQL-backed implementations of storage protocols
using asyncpg for async database operations and pgvector for vector similarity.

Available providers:
- PostgresVectorProvider: Vector storage with pgvector extension
- PostgresGraphProvider: Graph storage using adjacency list tables
- PostgresEventProvider: Event logging and audit trails
- PostgresFileTrackerProvider: File hash tracking for incremental indexing

Connection Management:
- PostgresConnectionManager: Centralized asyncpg pool management

Usage:
    from agent_vault.storage.providers.postgresql import (
        PostgresConnectionManager,
        PostgresVectorProvider,
    )

    # Create connection manager
    manager = PostgresConnectionManager(connection_string="postgresql://...")
    await manager.initialize()

    # Create providers with shared connection
    vector_provider = PostgresVectorProvider(manager, project_id="myproject")
    await vector_provider.initialize()

Requirements:
    - asyncpg: pip install asyncpg
    - pgvector extension in PostgreSQL: CREATE EXTENSION vector;
"""

from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Sequence, Union

from agent_vault.storage.providers.postgresql.connection import (
    PostgresConnectionManager,
)
from agent_vault.storage.providers.postgresql.events import (
    PostgresEventProvider,
)
from agent_vault.storage.providers.postgresql.file_tracker import (
    PostgresFileTrackerProvider,
)
from agent_vault.storage.providers.postgresql.graph import (
    PostgresGraphProvider,
)
from agent_vault.storage.providers.postgresql.schemas import (
    SchemaGenerator,
)
from agent_vault.storage.providers.postgresql.vector import (
    PostgresVectorProvider,
)
from agent_vault.storage.providers.postgresql.transaction import (
    TransactionCoordinator,
    transaction_scope,
)

if TYPE_CHECKING:
    from agent_vault.config import Config
    from agent_vault.database.results import SearchResult
    from agent_vault.models.document_chunk import DocumentChunk
    from agent_vault.models.graph_entity import GraphEntity
    from agent_vault.models.graph_relationship import GraphRelationship


class PostgreSQLProvider:
    """Unified PostgreSQL storage provider.

    This provider implements both VectorStorageProtocol and GraphStorageProtocol
    by delegating to specialized PostgreSQL implementations. It manages a
    shared connection pool and coordinates transactions across components.

    Attributes:
        SUPPORTED_ROLES: Storage roles this provider supports
    """

    SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset({"vector", "graph"})

    def __init__(
        self,
        config: "Config",
        project_id: str,
        connection_manager: Optional[PostgresConnectionManager] = None,
    ) -> None:
        """Initialize PostgreSQL provider.

        Args:
            config: Configuration instance
            project_id: Project ID for data isolation
            connection_manager: Optional shared connection manager
        """
        self._config = config
        self._project_id = project_id
        self._initialized = False

        # Create or use connection manager
        if connection_manager is None:
            # Try to get backend config if available
            backend_config = getattr(config.storage, "postgresql", None)
            if backend_config and hasattr(backend_config, "connection_string"):
                conn_config: Dict[str, Any] = {
                    "connection_string": backend_config.connection_string,
                    "pool_size": getattr(backend_config, "pool_size", 10),
                }
                similarity_metric = getattr(backend_config, "similarity_metric", None)
                if similarity_metric is not None:
                    conn_config["similarity_metric"] = similarity_metric
                self._conn_manager = PostgresConnectionManager.from_config(
                    conn_config,
                    table_prefix=getattr(backend_config, "table_prefix", "agv_"),
                )
            else:
                # Use a dummy or raise error if required for this provider
                connection_string = getattr(config.storage, "connection_string", None)
                if not connection_string:
                    # This will fail during initialize() if not provided, but allows instantiation for tests
                    connection_string = "postgresql://localhost/dummy"

                self._conn_manager = PostgresConnectionManager(
                    connection_string=connection_string,
                    table_prefix="agv_",
                )
        else:
            self._conn_manager = connection_manager

        # Sub-providers.
        #
        # TODO(#159 follow-up): this legacy ``__init__`` entry point
        # constructs the sub-providers without threading
        # ``embedding_strategy`` or ``adapter`` through, so they default
        # to ``"local"`` + ``DefaultPostgresAdapter``. Production routing
        # goes through ``BackendPoolManager`` /
        # ``PostgresVectorProvider.from_config``, which both pass the
        # configured strategy and the right adapter, so this matters
        # only for tests / direct callers. With the new strategy-aware
        # ``required_extensions``, the LOCAL fallthrough is at least
        # safe (only ``"vector"`` ensured) — but anyone wiring this
        # constructor against AlloyDB / RDS / Azure will silently miss
        # the cloud ML extension. Either remove this constructor or
        # thread strategy + adapter through.
        self._vector_provider = PostgresVectorProvider(
            self._conn_manager,
            project_id,
            embedding_dim=config.embeddings.default_dimensions,
        )
        self._graph_provider = PostgresGraphProvider(
            self._conn_manager,
            project_id,
            embedding_dim=config.embeddings.default_dimensions,
        )
        self._coordinator = TransactionCoordinator(
            self._conn_manager,
            self._vector_provider,
            self._graph_provider,
        )

    @classmethod
    async def from_config(
        cls,
        config: "Config",
        project_id: str,
    ) -> "PostgreSQLProvider":
        """Factory method to create provider from config."""
        provider = cls(config, project_id)
        await provider.initialize()
        return provider

    async def initialize(self) -> None:
        """Initialize connection pool and tables."""
        if self._initialized:
            return

        await self._conn_manager.initialize()
        await self._vector_provider.initialize()
        await self._graph_provider.initialize()

        self._initialized = True

    async def close(self) -> None:
        """Close connection pool."""
        if not self._initialized:
            return

        await self._conn_manager.close()
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    # =========================================================================
    # VectorStorageProtocol Delegation
    # =========================================================================

    async def upsert_chunks(
        self, chunks: Sequence["DocumentChunk"], project_id: str
    ) -> int:
        return await self._vector_provider.upsert_chunks(chunks, project_id)

    async def delete_chunks_by_file(self, file_path: str, project_id: str) -> int:
        return await self._vector_provider.delete_chunks_by_file(file_path, project_id)

    async def delete_chunks_by_ids(self, chunk_ids: List[str], project_id: str) -> int:
        return await self._vector_provider.delete_chunks_by_ids(chunk_ids, project_id)

    async def get_chunks_by_file(
        self, file_path: str, project_id: str
    ) -> List["DocumentChunk"]:
        return await self._vector_provider.get_chunks_by_file(file_path, project_id)

    async def vector_search(
        self,
        query_vector: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> List["SearchResult"]:
        return await self._vector_provider.vector_search(
            query_vector, limit, filters, project_id
        )

    async def fts_search(
        self,
        query: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> List["SearchResult"]:
        return await self._vector_provider.fts_search(query, limit, filters, project_id)

    async def hybrid_search(
        self,
        query_vector: List[float],
        query_text: str,
        limit: int = 10,
        vector_weight: float = 0.7,
        project_id: Optional[str] = None,
    ) -> List["SearchResult"]:
        return await self._vector_provider.hybrid_search(
            query_vector, query_text, limit, vector_weight, project_id
        )

    async def query(
        self,
        filters: Dict[str, Any],
        limit: int = 100,
        offset: int = 0,
        project_id: Optional[str] = None,
    ) -> List["DocumentChunk"]:
        return await self._vector_provider.query(filters, limit, offset, project_id)

    async def count(
        self, filters: Optional[Dict[str, Any]] = None, project_id: Optional[str] = None
    ) -> int:
        return await self._vector_provider.count(filters, project_id)

    async def entity_vector_search(
        self,
        query_vector: Union[str, List[float]],
        project_id: str,
        limit: int = 50,
        entity_type: Optional[str] = None,
    ) -> List["GraphEntity"]:
        return await self._vector_provider.entity_vector_search(
            query_vector=query_vector,
            project_id=project_id,
            limit=limit,
            entity_type=entity_type,
        )

    # =========================================================================
    # GraphStorageProtocol Delegation
    # =========================================================================

    async def upsert_entities(
        self, entities: Sequence["GraphEntity"], project_id: str
    ) -> int:
        return await self._graph_provider.upsert_entities(entities, project_id)

    async def get_entity(
        self, entity_id: str, project_id: str
    ) -> Optional["GraphEntity"]:
        return await self._graph_provider.get_entity(entity_id, project_id)

    async def get_entities_by_file(
        self, file_path: str, project_id: str
    ) -> List["GraphEntity"]:
        return await self._graph_provider.get_entities_by_file(file_path, project_id)

    async def get_entities_by_type(
        self, entity_type: str, project_id: str, limit: int = 100
    ) -> List["GraphEntity"]:
        return await self._graph_provider.get_entities_by_type(
            entity_type, project_id, limit
        )

    async def delete_entities_by_file(self, file_path: str, project_id: str) -> int:
        return await self._graph_provider.delete_entities_by_file(file_path, project_id)

    async def delete_entities_by_ids(
        self, entity_ids: List[str], project_id: str
    ) -> int:
        return await self._graph_provider.delete_entities_by_ids(entity_ids, project_id)

    async def query_entities(
        self,
        filters: Dict[str, Any],
        project_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List["GraphEntity"]:
        return await self._graph_provider.query_entities(
            filters, project_id, limit, offset
        )

    async def count_entities(
        self, filters: Optional[Dict[str, Any]] = None, project_id: Optional[str] = None
    ) -> int:
        return await self._graph_provider.count_entities(filters, project_id)

    async def upsert_relationships(
        self, relationships: Sequence["GraphRelationship"], project_id: str
    ) -> int:
        return await self._graph_provider.upsert_relationships(
            relationships, project_id
        )

    async def get_relationships_by_entity(
        self,
        entity_id: str,
        direction: str = "both",
        relationship_types: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> List["GraphRelationship"]:
        return await self._graph_provider.get_relationships_by_entity(
            entity_id, direction, relationship_types, project_id
        )

    async def delete_relationships_by_file(
        self, file_path: str, project_id: str
    ) -> int:
        return await self._graph_provider.delete_relationships_by_file(
            file_path, project_id
        )

    async def delete_relationships_by_entity(
        self, entity_id: str, project_id: str
    ) -> int:
        return await self._graph_provider.delete_relationships_by_entity(
            entity_id, project_id
        )

    async def delete_relationships_by_ids(
        self, relationship_ids: Sequence[str], project_id: str
    ) -> int:
        return await self._graph_provider.delete_relationships_by_ids(
            relationship_ids, project_id
        )

    async def query_relationships(
        self,
        filters: Dict[str, Any],
        project_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List["GraphRelationship"]:
        return await self._graph_provider.query_relationships(
            filters, project_id, limit, offset
        )

    async def get_neighbors(
        self,
        entity_id: str,
        direction: str = "both",
        depth: int = 1,
        relationship_types: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> List["GraphEntity"]:
        return await self._graph_provider.get_neighbors(
            entity_id, direction, depth, relationship_types, project_id
        )

    async def traverse(
        self,
        start_entity_id: str,
        max_depth: int = 2,
        relationship_types: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self._graph_provider.traverse(
            start_entity_id, max_depth, relationship_types, project_id
        )

    # =========================================================================
    # Maintenance & Health
    # =========================================================================

    async def health_check(self) -> Dict[str, Any]:
        return await self._vector_provider.health_check()

    async def run_maintenance(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        return await self._vector_provider.run_maintenance(project_id)


__all__ = [
    "PostgresConnectionManager",
    "PostgresEventProvider",
    "PostgresFileTrackerProvider",
    "PostgresGraphProvider",
    "PostgresVectorProvider",
    "PostgreSQLProvider",
    "SchemaGenerator",
    "TransactionCoordinator",
    "transaction_scope",
]
