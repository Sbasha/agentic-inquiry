"""Graph storage protocol for provider abstraction.

This module defines the protocol that all graph storage providers must implement.
Graph storage handles entities (nodes) and relationships (edges) in the knowledge graph.

Design principles:
- Minimal surface area: Only methods that vary across backends
- Capability-based: Check capabilities at runtime with isinstance()
- Canonical types: All methods use GraphEntity and GraphRelationship
- Async-only: All I/O operations are async
- Project isolation: All operations are scoped by project_id

See: .sessions/provider-framework/DESIGN_SPEC.md Section 4.2
"""
from __future__ import annotations

from typing import (
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    Sequence,
    runtime_checkable,
)

from agent_vault.models.graph_entity import GraphEntity
from agent_vault.models.graph_relationship import GraphRelationship


@runtime_checkable
class GraphStorageProtocol(Protocol):
    """Graph storage operations - comprehensive coverage of graph builder usage.

    This protocol defines the contract for graph storage providers. Implementations
    must support all methods for entity, relationship, and traversal operations.

    All graph data is scoped by project_id to enable multi-tenant isolation.

    Lifecycle:
        provider = await SomeGraphProvider.from_config(config)
        await provider.initialize()  # Ensure tables/indexes exist
        # ... use provider ...
        await provider.close()

    Example:
        class MyGraphProvider:
            async def initialize(self) -> None:
                # Initialize connection and create schema
                pass

            async def get_neighbors(
                self, entity_id: str, direction: str = "both", ...
            ) -> List[GraphEntity]:
                # Get neighboring entities via relationship traversal
                pass
    """

    # =========================================================================
    # Lifecycle Methods
    # =========================================================================

    async def initialize(self) -> None:
        """Initialize the storage backend connection.

        Must be called before any other operations. Safe to call multiple times
        (idempotent). Creates necessary tables, indexes, and schema if they
        don't exist.

        Raises:
            ConnectionError: If unable to connect to backend.
            RuntimeError: If initialization fails.

        Example:
            provider = MyGraphProvider(config)
            await provider.initialize()  # Ready to use
        """
        ...

    async def close(self) -> None:
        """Close the storage backend connection.

        Releases all resources including connections, caches, and file handles.
        Safe to call multiple times. After calling close(), the provider
        should not be used for any operations.

        Example:
            await provider.close()  # Resources released
        """
        ...

    # =========================================================================
    # Entity CRUD Operations
    # =========================================================================

    async def upsert_entities(
        self,
        entities: Sequence[GraphEntity],
        project_id: str,
    ) -> int:
        """Insert or update graph entities.

        If an entity with the same ID exists, it will be updated with the new
        values. Otherwise, a new entity is inserted. This operation is atomic
        for each entity but not across the entire batch.

        Args:
            entities: Sequence of GraphEntity objects to upsert. Each entity
                must have a unique 'id' field.
            project_id: Project scope for data isolation. Entities are stored
                within this project's namespace.

        Returns:
            Number of entities upserted (inserted or updated).

        Raises:
            ValueError: If entities contain invalid data or missing required fields.
            RuntimeError: If the upsert operation fails.

        Example:
            entities = [
                GraphEntity(id="func_1", name="process", type="function", ...),
                GraphEntity(id="class_1", name="Handler", type="class", ...),
            ]
            count = await provider.upsert_entities(entities, "my_project")
            assert count == 2
        """
        ...

    async def get_entity(
        self,
        entity_id: str,
        project_id: str,
    ) -> Optional[GraphEntity]:
        """Get a single entity by ID.

        Retrieves an entity by its unique identifier within the specified project.

        Args:
            entity_id: Unique entity identifier (UUID string).
            project_id: Project scope for data isolation.

        Returns:
            GraphEntity if found, None if no entity exists with the given ID.

        Example:
            entity = await provider.get_entity("func_123", "my_project")
            if entity:
                print(f"Found: {entity.name}")
            else:
                print("Entity not found")
        """
        ...

    async def get_entities_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> List[GraphEntity]:
        """Get all entities from a specific file.

        Retrieves all entities that were extracted from a given source file.
        Useful for file-based operations like re-indexing or deletion.

        Args:
            file_path: Path to the source file (relative or absolute).
            project_id: Project scope for data isolation.

        Returns:
            List of GraphEntity objects from the file. Empty list if no
            entities exist for the file.

        Example:
            entities = await provider.get_entities_by_file("src/auth.py", "my_project")
            print(f"Found {len(entities)} entities in auth.py")
        """
        ...

    async def get_entities_by_type(
        self,
        entity_type: str,
        project_id: str,
        limit: int = 100,
    ) -> List[GraphEntity]:
        """Get entities by type.

        Retrieves entities of a specific type (e.g., "function", "class").
        Results are limited to prevent memory issues with large datasets.

        Args:
            entity_type: Type of entities to retrieve. Should be a structural
                type (e.g., "function", "class", "method").
            project_id: Project scope for data isolation.
            limit: Maximum number of results to return. Default is 100.

        Returns:
            List of GraphEntity objects of the specified type.

        Example:
            classes = await provider.get_entities_by_type(
                "class", "my_project", limit=50
            )
            for cls in classes:
                print(f"Class: {cls.name}")
        """
        ...

    async def delete_entities_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> int:
        """Delete all entities from a specific file.

        Removes all entities that were extracted from a given source file.
        This is typically called during re-indexing to ensure stale entities
        are removed before new ones are added.

        Note: This does NOT automatically delete relationships involving
        these entities. Call delete_relationships_by_file() separately.

        Args:
            file_path: Path to the source file.
            project_id: Project scope for data isolation.

        Returns:
            Number of entities deleted.

        Example:
            deleted = await provider.delete_entities_by_file("src/old.py", "proj")
            print(f"Deleted {deleted} entities")
        """
        ...

    async def delete_entities_by_ids(
        self,
        entity_ids: List[str],
        project_id: str,
    ) -> int:
        """Delete entities by their IDs.

        Removes specific entities identified by their unique IDs.

        Note: This does NOT automatically delete relationships involving
        these entities. Handle orphaned relationships separately.

        Args:
            entity_ids: List of entity IDs to delete.
            project_id: Project scope for data isolation.

        Returns:
            Number of entities deleted (may be less than len(entity_ids)
            if some IDs don't exist).

        Example:
            deleted = await provider.delete_entities_by_ids(
                ["entity_1", "entity_2"], "my_project"
            )
        """
        ...

    # =========================================================================
    # Entity Query Operations (used by IndexingPipeline)
    # =========================================================================

    async def query_entities(
        self,
        filters: Dict[str, Any],
        project_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GraphEntity]:
        """Query entities with filters.

        Performs a filtered query on entities. Filters are key-value pairs
        that match against entity fields.

        Args:
            filters: Filter conditions as key-value pairs. Keys are field names,
                values are the expected values. All conditions are ANDed together.
                Supported operators depend on the backend implementation.
                Example: {"type": "function", "name": "process"}
            project_id: Project scope for data isolation.
            limit: Maximum number of results to return. Default is 100.
            offset: Number of results to skip for pagination. Default is 0.

        Returns:
            List of matching GraphEntity objects.

        Example:
            functions = await provider.query_entities(
                filters={"type": "function"},
                project_id="my_project",
                limit=50,
                offset=0
            )
        """
        ...

    async def count_entities(
        self,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> int:
        """Count entities matching filters.

        Returns the count of entities matching the specified filters.
        Useful for pagination and statistics.

        Args:
            filters: Optional filter conditions. If None, counts all entities.
            project_id: Optional project scope. If None, counts across all projects.

        Returns:
            Number of matching entities.

        Example:
            total = await provider.count_entities(project_id="my_project")
            functions = await provider.count_entities(
                {"type": "function"}, "my_project"
            )
            print(f"Total: {total}, Functions: {functions}")
        """
        ...

    # =========================================================================
    # Relationship CRUD Operations
    # =========================================================================

    async def upsert_relationships(
        self,
        relationships: Sequence[GraphRelationship],
        project_id: str,
    ) -> int:
        """Insert or update graph relationships.

        If a relationship with the same ID exists, it will be updated.
        Otherwise, a new relationship is inserted.

        Args:
            relationships: Sequence of GraphRelationship objects to upsert.
                Each relationship connects a source entity to a target entity.
            project_id: Project scope for data isolation.

        Returns:
            Number of relationships upserted.

        Raises:
            ValueError: If relationships contain invalid data.
            RuntimeError: If the upsert operation fails.

        Example:
            relationships = [
                GraphRelationship(
                    id="rel_1",
                    source_id="func_1",
                    target_id="func_2",
                    type="calls",
                    ...
                ),
            ]
            count = await provider.upsert_relationships(relationships, "my_project")
        """
        ...

    async def get_relationships_by_entity(
        self,
        entity_id: str,
        direction: str = "both",
        relationship_types: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> List[GraphRelationship]:
        """Get relationships for an entity.

        Retrieves all relationships where the specified entity is either
        the source or target, depending on the direction parameter.

        Args:
            entity_id: Entity to get relationships for.
            direction: Direction of relationships to retrieve:
                - "outgoing": Entity is the source (entity -> other)
                - "incoming": Entity is the target (other -> entity)
                - "both": Either direction (default)
            relationship_types: Optional list of relationship types to filter by
                (e.g., ["calls", "imports"]). If None, returns all types.
            project_id: Optional project scope. If None, searches all projects.

        Returns:
            List of GraphRelationship objects.

        Example:
            # Get all calls made by a function
            calls = await provider.get_relationships_by_entity(
                "func_123",
                direction="outgoing",
                relationship_types=["calls"]
            )
        """
        ...

    async def delete_relationships_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> int:
        """Delete all relationships from a specific file.

        Removes all relationships that were created from entities in the
        specified source file. This includes relationships where entities
        from this file are either the source or target.

        Args:
            file_path: Path to the source file.
            project_id: Project scope for data isolation.

        Returns:
            Number of relationships deleted.

        Example:
            deleted = await provider.delete_relationships_by_file(
                "src/old.py", "my_project"
            )
        """
        ...

    async def delete_relationships_by_entity(
        self,
        entity_id: str,
        project_id: str,
    ) -> int:
        """Delete all relationships for an entity.

        Removes all relationships where the specified entity is either
        the source or target. Call this before deleting an entity to
        avoid orphaned relationships.

        Args:
            entity_id: Entity to delete relationships for.
            project_id: Project scope for data isolation.

        Returns:
            Number of relationships deleted.

        Example:
            await provider.delete_relationships_by_entity("func_123", "my_project")
            await provider.delete_entities_by_ids(["func_123"], "my_project")
        """
        ...

    async def delete_relationships_by_ids(
        self,
        relationship_ids: Sequence[str],
        project_id: str,
    ) -> int:
        """Delete relationships by their IDs.

        Removes specific relationships identified by their unique IDs.
        Used by IndexingPipeline during file removal and graph cleanup.

        Args:
            relationship_ids: List of relationship IDs to delete.
            project_id: Project scope for data isolation.

        Returns:
            Number of relationships deleted.

        Example:
            deleted = await provider.delete_relationships_by_ids(
                ["rel_123", "rel_456"], "my_project"
            )
            print(f"Deleted {deleted} relationships")
        """
        ...

    # =========================================================================
    # Relationship Query Operations (used by GraphBuilder cleanup)
    # =========================================================================

    async def query_relationships(
        self,
        filters: Dict[str, Any],
        project_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GraphRelationship]:
        """Query relationships with filters.

        Performs a filtered query on relationships. Used by GraphBuilder
        cleanup operations and relationship analysis.

        Args:
            filters: Filter conditions as key-value pairs. Common filters:
                - {"type": "calls"}: All call relationships
                - {"source_id": "func_123"}: All outgoing from entity
                - {"target_id": "func_456"}: All incoming to entity
            project_id: Project scope for data isolation.
            limit: Maximum number of results to return. Default is 100.
            offset: Number of results to skip for pagination. Default is 0.

        Returns:
            List of matching GraphRelationship objects.

        Example:
            imports = await provider.query_relationships(
                filters={"type": "imports"},
                project_id="my_project",
                limit=1000
            )
        """
        ...

    async def count_relationships_by_type(
        self,
        project_id: str,
    ) -> Dict[str, int]:
        """Count relationships grouped by relationship type.

        Returns a dictionary mapping relationship types to their counts
        for the specified project. Used for project statistics and reporting.

        Args:
            project_id: Project scope for data isolation.

        Returns:
            Dictionary mapping relationship type to count, e.g.:
            {"imports": 50, "calls": 120, "contains": 30, "follows": 25}

        Example:
            counts = await provider.count_relationships_by_type("my_project")
            print(f"Contains: {counts.get('contains', 0)}")
            print(f"Follows: {counts.get('follows', 0)}")
        """
        ...

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

        Traverses the graph from a starting entity and returns all entities
        reachable within the specified depth.

        Args:
            entity_id: Starting entity ID for traversal.
            direction: Direction to traverse:
                - "outgoing": Follow outgoing relationships (source -> target)
                - "incoming": Follow incoming relationships (target <- source)
                - "both": Follow both directions (default)
            depth: How many hops to traverse. Default is 1 (immediate neighbors).
                Higher values explore further but may return many entities.
            relationship_types: Optional filter by relationship types.
                If None, traverses all relationship types.
            project_id: Optional project scope. If None, searches all projects.

        Returns:
            List of neighboring GraphEntity objects. Does not include the
            starting entity. Entities are deduplicated if reachable via
            multiple paths.

        Example:
            # Get all entities called by a function (1 hop)
            called = await provider.get_neighbors(
                "func_main",
                direction="outgoing",
                relationship_types=["calls"]
            )

            # Get extended call graph (2 hops)
            extended = await provider.get_neighbors(
                "func_main",
                direction="outgoing",
                depth=2,
                relationship_types=["calls"]
            )
        """
        ...

    async def traverse(
        self,
        start_entity_id: str,
        max_depth: int = 2,
        relationship_types: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Traverse the graph from a starting entity.

        Performs a comprehensive graph traversal returning both entities
        and relationships. More detailed than get_neighbors().

        Args:
            start_entity_id: Starting entity ID for traversal.
            max_depth: Maximum traversal depth. Default is 2.
            relationship_types: Optional filter by relationship types.
            project_id: Optional project scope.

        Returns:
            Dict with traversal result containing:
                - "entities": List[GraphEntity] - All discovered entities
                - "relationships": List[GraphRelationship] - All traversed edges
                - "start_entity": GraphEntity - The starting entity
                - "depth_reached": int - Actual depth traversed
                - "paths": Optional structure showing traversal paths

        Example:
            result = await provider.traverse(
                "class_SearchService",
                max_depth=3,
                relationship_types=["calls", "imports", "inherits"]
            )
            print(f"Found {len(result['entities'])} entities")
            print(f"Found {len(result['relationships'])} relationships")
        """
        ...

    # ``entity_vector_search`` moved to :class:`VectorStorageProtocol` —
    # it's a vector-space op, and separating it lets the graph backend be
    # a pure-graph store (e.g. Kuzu) without having to stub vector search.


# =============================================================================
# Capability Detection Helpers
# =============================================================================


def has_graph_storage(adapter: object) -> bool:
    """Check if adapter supports graph storage operations.

    Args:
        adapter: Adapter instance to check.

    Returns:
        True if adapter implements GraphStorageProtocol.

    Example:
        if has_graph_storage(provider):
            await provider.upsert_entities(entities, project_id)
    """
    return isinstance(adapter, GraphStorageProtocol)


__all__ = [
    "GraphStorageProtocol",
    "has_graph_storage",
]
