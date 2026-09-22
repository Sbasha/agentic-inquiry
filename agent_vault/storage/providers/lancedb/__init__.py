"""LanceDB storage providers for agent_vault.

This package provides LanceDB-backed implementations of storage protocols
for vector similarity search and knowledge graph operations.

Available providers:
- LanceDBVectorProvider: Vector storage with similarity search
- LanceDBGraphProvider: Graph storage for entities and relationships

Connection Management:
- LanceDBConnectionManager: Centralized connection and lifecycle management

Backward Compatibility:
- LanceDBProvider: Combined vector + graph provider (deprecated, use separate providers)

Usage:
    from agent_vault.storage.providers.lancedb import (
        LanceDBConnectionManager,
        LanceDBVectorProvider,
        LanceDBGraphProvider,
    )

    # Create connection manager
    manager = LanceDBConnectionManager(config, project_id="myproject")
    await manager.initialize()  # Creates directories and tables

    # Create providers with shared connection
    vector_provider = LanceDBVectorProvider(manager)
    graph_provider = LanceDBGraphProvider(manager)

    # Use providers
    await vector_provider.upsert_chunks(chunks, "myproject")
    await graph_provider.upsert_entities(entities, "myproject")

    # Clean shutdown
    await manager.close()

Legacy Usage (deprecated):
    from agent_vault.storage.providers.lancedb import LanceDBProvider

    provider = await LanceDBProvider.from_config(config, "myproject")
    await provider.initialize()
    # ... use provider for both vector and graph operations ...
    await provider.close()
"""

from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Sequence, Union

from agent_vault.storage.providers.lancedb.connection import (
    LanceDBConnectionManager,
)
from agent_vault.storage.providers.lancedb.graph import (
    LanceDBGraphProvider,
)
from agent_vault.storage.providers.lancedb.maintenance import (
    LanceDBMaintenanceOperations,
)
from agent_vault.storage.providers.lancedb.vector import (
    LanceDBVectorProvider,
)

if TYPE_CHECKING:
    from datetime import timedelta

    from agent_vault.config import Config
    from agent_vault.database.results import SearchResult
    from agent_vault.models.document_chunk import DocumentChunk
    from agent_vault.models.graph_entity import GraphEntity
    from agent_vault.models.graph_relationship import GraphRelationship


class LanceDBProvider:
    """Combined LanceDB provider for backward compatibility.

    This class provides a unified interface that combines vector and graph
    operations into a single provider. It maintains backward compatibility
    with existing code that uses the monolithic LanceDBProvider.

    Note:
        This class is DEPRECATED. New code should use the separate
        LanceDBVectorProvider and LanceDBGraphProvider classes.

    The provider:
    - Implements VectorStorageProtocol: Vector search and document storage
    - Implements GraphStorageProtocol: Knowledge graph operations
    - Implements MaintenanceProtocol: Index optimization

    Attributes:
        SUPPORTED_ROLES: Storage roles this provider supports

    Example:
        # Legacy usage (deprecated)
        provider = await LanceDBProvider.from_config(config, "my_project")
        await provider.initialize()
        results = await provider.vector_search(query_vector, limit=10)
        await provider.close()

        # Recommended usage
        manager = LanceDBConnectionManager(config, "my_project")
        await manager.initialize()
        vector = LanceDBVectorProvider(manager)
        graph = LanceDBGraphProvider(manager)
    """

    SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset({"vector", "graph"})

    def __init__(
        self,
        config: "Config",
        project_id: str,
        db_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize LanceDB provider.

        Args:
            config: Configuration instance
            project_id: Project ID for data isolation
            db_manager: Optional pre-configured LanceDBManager
            **kwargs: Additional backend configuration (ignored)
        """
        self._config = config
        self._project_id = project_id
        self._initialized = False

        # Create internal connection manager
        self._connection_manager = LanceDBConnectionManager(
            config, project_id, db_manager
        )

        # Create sub-providers (lazily initialized)
        self._vector_provider: Optional[LanceDBVectorProvider] = None
        self._graph_provider: Optional[LanceDBGraphProvider] = None
        self._maintenance: Optional[LanceDBMaintenanceOperations] = None

    @classmethod
    async def from_config(
        cls,
        config: "Config",
        project_id: str,
    ) -> "LanceDBProvider":
        """Create provider from configuration.

        Note: This method is DEPRECATED. Use LanceDBConnectionManager
        with separate providers instead.

        Args:
            config: Configuration instance
            project_id: Project ID for data isolation

        Returns:
            Configured LanceDBProvider instance
        """
        from agent_vault.database.lancedb_manager import LanceDBManager

        db_manager = LanceDBManager.from_config(config, project_id=project_id)
        return cls(config, project_id, db_manager)

    async def initialize(self) -> None:
        """Initialize the storage backend.

        Ensures database connection and tables exist.
        This method is idempotent.
        """
        if self._initialized:
            return

        await self._connection_manager.initialize()

        # Create sub-providers
        self._vector_provider = LanceDBVectorProvider(self._connection_manager)
        self._graph_provider = LanceDBGraphProvider(self._connection_manager)
        self._maintenance = LanceDBMaintenanceOperations(self._connection_manager)

        self._initialized = True

    async def close(self) -> None:
        """Close the storage backend.

        Releases connections and resources.
        """
        if not self._initialized:
            return

        await self._connection_manager.close()
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        """Check if the provider is initialized."""
        return self._initialized

    # =========================================================================
    # VectorStorageProtocol - delegated to LanceDBVectorProvider
    # =========================================================================

    async def upsert_chunks(
        self,
        chunks: Sequence["DocumentChunk"],
        project_id: str,
    ) -> int:
        """Insert or update document chunks."""
        if self._vector_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._vector_provider.upsert_chunks(chunks, project_id)

    async def delete_chunks_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> int:
        """Delete all chunks from a specific file."""
        if self._vector_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._vector_provider.delete_chunks_by_file(file_path, project_id)

    async def delete_chunks_by_ids(
        self,
        chunk_ids: List[str],
        project_id: str,
    ) -> int:
        """Delete chunks by their IDs."""
        if self._vector_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._vector_provider.delete_chunks_by_ids(chunk_ids, project_id)

    async def get_chunks_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> List["DocumentChunk"]:
        """Get all chunks from a specific file."""
        if self._vector_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._vector_provider.get_chunks_by_file(file_path, project_id)

    async def vector_search(
        self,
        query_vector: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> List["SearchResult"]:
        """Perform vector similarity search."""
        if self._vector_provider is None:
            raise RuntimeError("Provider not initialized")
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
        """Perform full-text search."""
        if self._vector_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._vector_provider.fts_search(query, limit, filters, project_id)

    async def hybrid_search(
        self,
        query_vector: List[float],
        query_text: str,
        limit: int = 10,
        vector_weight: float = 0.7,
        project_id: Optional[str] = None,
    ) -> List["SearchResult"]:
        """Perform hybrid vector + FTS search."""
        if self._vector_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._vector_provider.hybrid_search(
            query_vector, query_text, limit, vector_weight, project_id
        )

    async def entity_vector_search(
        self,
        query_vector: Union[str, List[float]],
        project_id: str,
        limit: int = 50,
        entity_type: Optional[str] = None,
    ) -> List["GraphEntity"]:
        """Delegate entity vector search to the vector sub-provider.

        Signature mirrors ``VectorStorageProtocol`` (``Union[str,
        List[float]]``) — the sub-provider raises ``TypeError`` if given
        a ``str`` since LanceDB has no server-side embedding.
        """
        if self._vector_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._vector_provider.entity_vector_search(
            query_vector=query_vector,
            project_id=project_id,
            limit=limit,
            entity_type=entity_type,
        )

    async def query(
        self,
        filters: Dict[str, Any],
        limit: int = 100,
        offset: int = 0,
        project_id: Optional[str] = None,
    ) -> List["DocumentChunk"]:
        """Query chunks with filters."""
        if self._vector_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._vector_provider.query(filters, limit, offset, project_id)

    async def count(
        self,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> int:
        """Count chunks matching filters."""
        if self._vector_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._vector_provider.count(filters, project_id)

    async def query_across_projects(
        self,
        table_name: str,
        project_ids: Sequence[str],
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query data across multiple projects."""
        if self._vector_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._vector_provider.query_across_projects(
            table_name, project_ids, filters, limit
        )

    async def list_tables(self) -> List[str]:
        """List all tables in the storage."""
        if self._vector_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._vector_provider.list_tables()

    async def table_exists(self, table_name: str) -> bool:
        """Check if a table exists."""
        if self._vector_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._vector_provider.table_exists(table_name)

    # =========================================================================
    # GraphStorageProtocol - delegated to LanceDBGraphProvider
    # =========================================================================

    async def upsert_entities(
        self,
        entities: Sequence["GraphEntity"],
        project_id: str,
    ) -> int:
        """Insert or update graph entities."""
        if self._graph_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._graph_provider.upsert_entities(entities, project_id)

    async def get_entity(
        self,
        entity_id: str,
        project_id: str,
    ) -> Optional["GraphEntity"]:
        """Retrieve an entity by ID."""
        if self._graph_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._graph_provider.get_entity(entity_id, project_id)

    async def get_entities_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> List["GraphEntity"]:
        """Get all entities from a specific file."""
        if self._graph_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._graph_provider.get_entities_by_file(file_path, project_id)

    async def get_entities_by_type(
        self,
        entity_type: str,
        project_id: str,
        limit: int = 100,
    ) -> List["GraphEntity"]:
        """Get entities by type."""
        if self._graph_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._graph_provider.get_entities_by_type(
            entity_type, project_id, limit
        )

    async def delete_entities_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> int:
        """Delete all entities from a specific file."""
        if self._graph_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._graph_provider.delete_entities_by_file(file_path, project_id)

    async def delete_entities_by_ids(
        self,
        entity_ids: List[str],
        project_id: str,
    ) -> int:
        """Delete entities by their IDs."""
        if self._graph_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._graph_provider.delete_entities_by_ids(entity_ids, project_id)

    async def query_entities(
        self,
        filters: Dict[str, Any],
        project_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query entities with arbitrary filters."""
        if self._graph_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._graph_provider.query_entities(
            filters, project_id, limit, offset
        )

    async def count_entities(
        self,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> int:
        """Count entities matching filters."""
        if self._graph_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._graph_provider.count_entities(filters, project_id)

    async def count_relationships_by_type(
        self,
        project_id: str,
    ) -> Dict[str, int]:
        """Count relationships by type."""
        if self._graph_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._graph_provider.count_relationships_by_type(project_id)

    async def upsert_relationships(
        self,
        relationships: Sequence["GraphRelationship"],
        project_id: str,
    ) -> int:
        """Insert or update graph relationships."""
        if self._graph_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._graph_provider.upsert_relationships(relationships, project_id)

    async def get_relationships_by_entity(
        self,
        entity_id: str,
        direction: str = "both",
        relationship_types: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> List["GraphRelationship"]:
        """Get relationships for an entity."""
        if self._graph_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._graph_provider.get_relationships_by_entity(
            entity_id, direction, relationship_types, project_id
        )

    async def delete_relationships_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> int:
        """Delete all relationships from a specific file."""
        if self._graph_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._graph_provider.delete_relationships_by_file(
            file_path, project_id
        )

    async def delete_relationships_by_entity(
        self,
        entity_id: str,
        project_id: str,
    ) -> int:
        """Delete all relationships for an entity."""
        if self._graph_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._graph_provider.delete_relationships_by_entity(
            entity_id, project_id
        )

    async def delete_relationships_by_ids(
        self,
        relationship_ids: Sequence[str],
        project_id: str,
    ) -> int:
        """Delete relationships by their IDs."""
        if self._graph_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._graph_provider.delete_relationships_by_ids(
            relationship_ids, project_id
        )

    async def query_relationships(
        self,
        filters: Dict[str, Any],
        project_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query relationships with arbitrary filters."""
        if self._graph_provider is None:
            raise RuntimeError("Provider not initialized")
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
        """Get neighboring entities."""
        if self._graph_provider is None:
            raise RuntimeError("Provider not initialized")
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
        """Traverse the graph from a starting entity."""
        if self._graph_provider is None:
            raise RuntimeError("Provider not initialized")
        return await self._graph_provider.traverse(
            start_entity_id, max_depth, relationship_types, project_id
        )

    # =========================================================================
    # MaintenanceProtocol - delegated to LanceDBMaintenanceOperations
    # =========================================================================

    async def health_check(self) -> Dict[str, Any]:
        """Check provider health."""
        if self._maintenance is None:
            return {
                "status": "unhealthy",
                "healthy": False,
                "error": "Provider not initialized",
            }
        return await self._maintenance.health_check()

    async def run_maintenance(
        self,
        table_names: Optional[List[str]] = None,
        cleanup_older_than: Optional["timedelta"] = None,
    ) -> Dict[str, Any]:
        """Run maintenance tasks."""
        if self._maintenance is None:
            raise RuntimeError("Provider not initialized")
        return await self._maintenance.run_maintenance(table_names, cleanup_older_than)

    async def compact(self) -> Dict[str, Any]:
        """Compact storage to reclaim space."""
        if self._maintenance is None:
            raise RuntimeError("Provider not initialized")
        return await self._maintenance.compact()

    async def validate_integrity(
        self,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate database integrity.

        Args:
            project_id: Optional project ID (for protocol compliance)

        Returns:
            Dict with validation results
        """
        if self._maintenance is None:
            raise RuntimeError("Provider not initialized")
        return await self._maintenance.validate_integrity()

    async def cleanup_orphaned_data(
        self,
        project_id: str,
    ) -> int:
        """Clean up orphaned data."""
        if self._maintenance is None:
            raise RuntimeError("Provider not initialized")
        return await self._maintenance.cleanup_orphaned_data(project_id)


__all__ = [
    # Connection management
    "LanceDBConnectionManager",
    # Specialized providers
    "LanceDBVectorProvider",
    "LanceDBGraphProvider",
    # Maintenance
    "LanceDBMaintenanceOperations",
    # Backward-compatible combined provider
    "LanceDBProvider",
]
