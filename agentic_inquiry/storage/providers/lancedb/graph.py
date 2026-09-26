"""LanceDB graph storage provider.

This module provides the LanceDBGraphProvider class that implements
GraphStorageProtocol using LanceDB as the storage backend.

The provider delegates lifecycle management to LanceDBConnectionManager
and focuses on graph-specific operations (entities and relationships).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Sequence

from agentic_inquiry.models.graph_entity import GraphEntity
from agentic_inquiry.models.graph_relationship import GraphRelationship
from agentic_inquiry.storage.providers.lancedb.entity_rows import (
    GRAPH_ENTITIES_TABLE,
    dict_to_graph_entity,
)

if TYPE_CHECKING:
    from agentic_inquiry.storage.providers.lancedb.connection import (
        LanceDBConnectionManager,
    )

logger = logging.getLogger(__name__)

# Table constants
GRAPH_RELATIONSHIPS_TABLE = "graph_relationships"


class LanceDBGraphProvider:
    """LanceDB implementation of GraphStorageProtocol.

    This provider implements knowledge graph operations using LanceDB.
    It delegates connection management to LanceDBConnectionManager.

    Attributes:
        connection_manager: Shared connection manager
        SUPPORTED_ROLES: Storage roles this provider supports

    Example:
        >>> manager = LanceDBConnectionManager(config, "my-project")
        >>> await manager.initialize()
        >>> graph_provider = LanceDBGraphProvider(manager)
        >>> await graph_provider.upsert_entities(entities, "my-project")
    """

    SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset({"graph"})

    def __init__(
        self,
        connection_manager: "LanceDBConnectionManager",
    ) -> None:
        """Initialize graph provider.

        Args:
            connection_manager: Initialized LanceDBConnectionManager
        """
        self._connection_manager = connection_manager

    @property
    def is_initialized(self) -> bool:
        """Check if the provider is ready for operations."""
        return self._connection_manager.is_initialized

    @property
    def _db_manager(self):
        """Get the underlying database manager."""
        return self._connection_manager.db_manager

    @property
    def _project_id(self) -> str:
        """Get the project ID from connection manager."""
        return self._connection_manager.project_id

    @property
    def _max_query_limit(self) -> int:
        """Row cap for aggregations that pull-then-count.

        LanceDB has no GROUP BY, so ``count_relationships_by_type``
        materialises rows and buckets in Python. Driven by
        ``storage.max_query_limit`` (default 100,000) so operators can
        raise the ceiling without touching provider code. When the
        result count hits the ceiling, the caller logs a warning — see
        ``count_relationships_by_type`` below.
        """
        return self._connection_manager.config.storage.max_query_limit

    # =========================================================================
    # GraphStorageProtocol Implementation - Entities
    # =========================================================================

    async def upsert_entities(
        self,
        entities: Sequence[GraphEntity],
        project_id: str,
    ) -> int:
        """Insert or update graph entities.

        Args:
            entities: Entities to upsert
            project_id: Project ID for isolation

        Returns:
            Number of entities upserted
        """
        if not entities:
            return 0

        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        # Convert entities to dicts
        records = []
        for entity in entities:
            # Get type as string
            type_val = entity.type
            if hasattr(type_val, "value"):
                type_val = type_val.value

            record = {
                "id": entity.id,
                "project_id": project_id,
                "name": entity.name,
                "type": type_val,
                "domain": getattr(entity, "domain", "code"),
                "file_path": entity.file_path,
                "doc_id": entity.doc_id,
                "vector": entity.vector,
                "line_start": entity.line_start,
                "line_end": entity.line_end,
                "pagerank": entity.pagerank,
                "betweenness": entity.betweenness,
                "community_id": entity.community_id,
                "has_ranking_signals": entity.has_ranking_signals,
            }
            records.append(record)

        await self._db_manager.add_graph_entities(records)
        return len(records)

    async def get_entity(
        self,
        entity_id: str,
        project_id: str,
    ) -> Optional[GraphEntity]:
        """Retrieve an entity by ID.

        Args:
            entity_id: ID of the entity
            project_id: Project ID for isolation

        Returns:
            Entity if found, None otherwise
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        # Query for specific entity
        results = await self._db_manager.query_entities(
            filters={"id": entity_id, "project_id": project_id},
            limit=1,
            project_id=project_id,
        )

        if results:
            return self._dict_to_graph_entity(results[0])

        return None

    async def get_entities_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> List[GraphEntity]:
        """Get all entities from a specific file.

        Args:
            file_path: Path to the source file
            project_id: Project ID for isolation

        Returns:
            List of entities from the file
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        results = await self._db_manager.query_entities(
            filters={"file_path": file_path, "project_id": project_id},
            limit=10000,
            project_id=project_id,
        )

        entities = []
        for record in results:
            entity = self._dict_to_graph_entity(record)
            if entity:
                entities.append(entity)

        return entities

    async def get_entities_by_type(
        self,
        entity_type: str,
        project_id: str,
        limit: int = 100,
    ) -> List[GraphEntity]:
        """Get entities by type.

        Args:
            entity_type: Type of entities to retrieve
            project_id: Project ID for isolation
            limit: Maximum number of results

        Returns:
            List of entities of the specified type
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        results = await self._db_manager.query_entities(
            filters={"type": entity_type, "project_id": project_id},
            limit=limit,
            project_id=project_id,
        )

        entities = []
        for record in results:
            entity = self._dict_to_graph_entity(record)
            if entity:
                entities.append(entity)

        return entities

    async def delete_entities_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> int:
        """Delete all entities from a specific file.

        Args:
            file_path: Path to the source file
            project_id: Project ID for isolation

        Returns:
            Number of entities deleted
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        # Get entities first to count and get IDs
        entities = await self.get_entities_by_file(file_path, project_id)
        if not entities:
            return 0

        entity_ids = [entity.id for entity in entities]
        await self._db_manager.delete_graph_entities(entity_ids)
        return len(entity_ids)

    async def delete_entities_by_ids(
        self,
        entity_ids: List[str],
        project_id: str,
    ) -> int:
        """Delete entities by their IDs.

        Also cascade deletes relationships where deleted entities are
        source or target, respecting project isolation.

        Args:
            entity_ids: IDs of entities to delete
            project_id: Project ID for isolation

        Returns:
            Number of entities deleted
        """
        if not entity_ids:
            return 0

        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        # Cascade delete relationships involving these entities
        for entity_id in entity_ids:
            await self.delete_relationships_by_entity(entity_id, project_id)

        # Delete the entities
        await self._db_manager.delete_graph_entities(entity_ids)
        return len(entity_ids)

    async def query_entities(
        self,
        filters: Dict[str, Any],
        project_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query entities with arbitrary filters.

        Args:
            filters: Filter conditions as key-value pairs
            project_id: Project ID for isolation
            limit: Maximum number of results
            offset: Number of results to skip (not currently supported)

        Returns:
            List of entity dictionaries matching the query
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        # Note: offset not currently implemented in LanceDBManager
        return await self._db_manager.query_entities(
            filters=filters,
            limit=limit,
            project_id=project_id,
        )

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
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        effective_project_id = project_id or self._project_id
        return await self._db_manager.count_records(
            table_name=GRAPH_ENTITIES_TABLE,
            filters=filters,
            project_id=effective_project_id,
        )

    # =========================================================================
    # GraphStorageProtocol Implementation - Relationships
    # =========================================================================

    async def upsert_relationships(
        self,
        relationships: Sequence[GraphRelationship],
        project_id: str,
    ) -> int:
        """Insert or update graph relationships.

        Args:
            relationships: Relationships to upsert
            project_id: Project ID for isolation

        Returns:
            Number of relationships upserted
        """
        if not relationships:
            return 0

        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        # Convert relationships to dicts
        records = []
        for rel in relationships:
            # Get type as string
            type_val = rel.type
            if hasattr(type_val, "value"):
                type_val = type_val.value

            record = {
                "id": rel.id,
                "project_id": project_id,
                "source_id": rel.source_id,
                "target_id": rel.target_id,
                "type": type_val,
                "vector": rel.vector,
                "metadata": rel.metadata,
            }
            records.append(record)

        await self._db_manager.add_graph_relationships(records)
        return len(records)

    async def get_relationships_by_entity(
        self,
        entity_id: str,
        direction: str = "both",
        relationship_types: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> List[GraphRelationship]:
        """Get relationships for an entity.

        Args:
            entity_id: ID of the entity
            direction: "outgoing", "incoming", or "both"
            relationship_types: Optional filter by relationship types
            project_id: Project ID for isolation

        Returns:
            List of relationships
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        effective_project_id = project_id or self._project_id

        # Build filters based on direction
        all_relationships: List[GraphRelationship] = []

        if direction in ("outgoing", "both"):
            # Get relationships where entity is source
            filters: Dict[str, Any] = {
                "source_id": entity_id,
                "project_id": effective_project_id,
            }
            if relationship_types:
                filters["type"] = relationship_types

            results = await self._db_manager.query_relationships(
                filters=filters,
                limit=10000,
                project_id=effective_project_id,
            )

            for record in results:
                rel = self._dict_to_graph_relationship(record)
                if rel:
                    all_relationships.append(rel)

        if direction in ("incoming", "both"):
            # Get relationships where entity is target
            filters = {"target_id": entity_id, "project_id": effective_project_id}
            if relationship_types:
                filters["type"] = relationship_types

            results = await self._db_manager.query_relationships(
                filters=filters,
                limit=10000,
                project_id=effective_project_id,
            )

            for record in results:
                rel = self._dict_to_graph_relationship(record)
                if rel and rel.id not in {r.id for r in all_relationships}:
                    all_relationships.append(rel)

        return all_relationships

    async def count_relationships_by_type(
        self,
        project_id: str,
    ) -> Dict[str, int]:
        """Count relationships grouped by relationship type.

        Uses the manager's dict-based filter API rather than building a
        raw ``.where()`` string — values flow through the shared filter
        translator (``LanceDBFilterAdapter``) so project_ids / other
        filter values don't need local escaping and can't malform the
        query.

        Args:
            project_id: Project ID for isolation

        Returns:
            Dictionary mapping relationship type to count
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        try:
            limit = self._max_query_limit
            results = await self._db_manager.query_relationships(
                filters={"project_id": project_id},
                limit=limit,
                project_id=project_id,
            )

            # Count by type
            counts: Dict[str, int] = {}
            for record in results:
                rel_type = record.get("type", "unknown")
                counts[rel_type] = counts.get(rel_type, 0) + 1

            # ``limit > 0`` guard: a misconfigured ``max_query_limit=0``
            # (or negative) would otherwise fire a spurious truncation
            # warning on every call. ``query_relationships`` is bounded
            # by ``limit=`` upstream so ``len(results) == limit`` is the
            # saturated case — we can't distinguish "got exactly limit
            # rows" from "got more and truncated" without over-fetching,
            # so treat equality as the honest conservative signal.
            if limit > 0 and len(results) == limit:
                logger.warning(
                    "count_relationships_by_type hit max_query_limit=%d for "
                    "project %s — counts may be truncated. Raise "
                    "storage.max_query_limit or migrate the graph role to "
                    "Postgres for accurate aggregation.",
                    limit,
                    project_id,
                )

            return counts
        except Exception as e:
            logger.warning("Failed to count relationships by type: %s", e)
            return {}

    async def delete_relationships_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> int:
        """Delete all relationships from a specific file.

        Args:
            file_path: Path to the source file
            project_id: Project ID for isolation

        Returns:
            Number of relationships deleted
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        # Get entities for this file first
        entities = await self.get_entities_by_file(file_path, project_id)
        if not entities:
            return 0

        # Delete relationships for each entity
        deleted_count = 0
        for entity in entities:
            count = await self.delete_relationships_by_entity(entity.id, project_id)
            deleted_count += count

        return deleted_count

    async def delete_relationships_by_entity(
        self,
        entity_id: str,
        project_id: str,
    ) -> int:
        """Delete all relationships for an entity.

        Args:
            entity_id: Entity to delete relationships for
            project_id: Project ID for isolation

        Returns:
            Number of relationships deleted
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        # Get all relationships for this entity
        relationships = await self.get_relationships_by_entity(
            entity_id=entity_id,
            direction="both",
            project_id=project_id,
        )

        if not relationships:
            return 0

        rel_ids = [rel.id for rel in relationships]
        await self._db_manager.delete_graph_relationships(rel_ids)
        return len(rel_ids)

    async def delete_relationships_by_ids(
        self,
        relationship_ids: Sequence[str],
        project_id: str,
    ) -> int:
        """Delete relationships by their IDs.

        Args:
            relationship_ids: List of relationship IDs to delete
            project_id: Project ID for isolation

        Returns:
            Number of relationships deleted
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        if not relationship_ids:
            return 0

        await self._db_manager.delete_graph_relationships(list(relationship_ids))
        return len(relationship_ids)

    async def query_relationships(
        self,
        filters: Dict[str, Any],
        project_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query relationships with arbitrary filters.

        Args:
            filters: Filter conditions as key-value pairs
            project_id: Project ID for isolation
            limit: Maximum number of results
            offset: Number of results to skip (not currently supported)

        Returns:
            List of relationship dictionaries matching the query
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        # Map filter keys for compatibility:
        # - 'relationship_type' is used by callers (e.g., relationship_resolver)
        # - 'type' is the actual LanceDB column name (schema uses 'type')
        mapped_filters = {}
        if filters:
            for key, value in filters.items():
                if key == "relationship_type":
                    mapped_filters["type"] = value
                else:
                    mapped_filters[key] = value
        else:
            mapped_filters = filters

        # Note: offset not currently implemented in LanceDBManager
        return await self._db_manager.query_relationships(
            filters=mapped_filters,
            limit=limit,
            project_id=project_id,
        )

    # =========================================================================
    # Graph Traversal Operations
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
            project_id: Project ID for isolation

        Returns:
            List of neighboring entities
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        effective_project_id = project_id or self._project_id

        # BFS traversal
        visited: set[str] = set()
        current_level = {entity_id}
        neighbors: List[GraphEntity] = []

        for _ in range(depth):
            next_level: set[str] = set()

            for eid in current_level:
                if eid in visited:
                    continue
                visited.add(eid)

                # Get relationships for this entity
                rels = await self.get_relationships_by_entity(
                    entity_id=eid,
                    direction=direction,
                    relationship_types=relationship_types,
                    project_id=effective_project_id,
                )

                for rel in rels:
                    # Get the other end of the relationship
                    other_id = rel.target_id if rel.source_id == eid else rel.source_id
                    if other_id not in visited:
                        next_level.add(other_id)

            current_level = next_level

        # Fetch all neighbor entities
        for neighbor_id in current_level:
            if neighbor_id != entity_id and neighbor_id not in {e.id for e in neighbors}:
                entity = await self.get_entity(neighbor_id, effective_project_id)
                if entity:
                    neighbors.append(entity)

        return neighbors

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
            relationship_types: Types of relationships to follow
            project_id: Project ID for isolation

        Returns:
            Dict with entities, relationships, and traversal info
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        effective_project_id = project_id or self._project_id

        # BFS traversal collecting all entities and relationships
        visited: set[str] = set()
        current_level = {start_entity_id}
        all_entities: List[GraphEntity] = []
        all_relationships: List[GraphRelationship] = []
        depth_map: Dict[str, int] = {start_entity_id: 0}

        # Get start entity
        start_entity = await self.get_entity(start_entity_id, effective_project_id)
        if start_entity:
            all_entities.append(start_entity)

        for current_depth in range(max_depth):
            next_level: set[str] = set()

            for eid in current_level:
                if eid in visited:
                    continue
                visited.add(eid)

                # Get relationships
                rels = await self.get_relationships_by_entity(
                    entity_id=eid,
                    direction="both",
                    relationship_types=relationship_types,
                    project_id=effective_project_id,
                )

                for rel in rels:
                    if rel.id not in {r.id for r in all_relationships}:
                        all_relationships.append(rel)

                    # Get the other end
                    other_id = rel.target_id if rel.source_id == eid else rel.source_id
                    if other_id not in visited:
                        next_level.add(other_id)
                        if other_id not in depth_map:
                            depth_map[other_id] = current_depth + 1

            # Fetch entities for next level
            for neighbor_id in next_level:
                if neighbor_id not in {e.id for e in all_entities}:
                    entity = await self.get_entity(neighbor_id, effective_project_id)
                    if entity:
                        all_entities.append(entity)

            current_level = next_level

        return {
            "entities": all_entities,
            "relationships": all_relationships,
            "depth_map": depth_map,
            "start_entity_id": start_entity_id,
            "max_depth": max_depth,
        }

    # ``entity_vector_search`` moved to :class:`LanceDBVectorProvider` —
    # vector similarity is a vector-space concern even though the
    # ``graph_entities`` table sits in this package.

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _dict_to_graph_entity(self, record: Dict[str, Any]) -> Optional[GraphEntity]:
        """Convert a LanceDB row dict to a :class:`GraphEntity`.

        Delegates to the shared :func:`dict_to_graph_entity` helper so the
        vector provider (which reads the same ``graph_entities`` table for
        ``entity_vector_search``) uses identical conversion logic.
        """
        return dict_to_graph_entity(record)

    def _dict_to_graph_relationship(
        self, record: Dict[str, Any]
    ) -> Optional[GraphRelationship]:
        """Convert a dict record to GraphRelationship.

        Args:
            record: Dict from database

        Returns:
            GraphRelationship or None if conversion fails
        """
        try:
            return GraphRelationship(
                id=record.get("id", ""),
                project_id=record.get("project_id", ""),
                source_id=record.get("source_id", ""),
                target_id=record.get("target_id", ""),
                type=record.get("type", "relates_to"),
                vector=record.get("vector", []),
                metadata=record.get("metadata"),
            )
        except Exception as e:
            logger.warning("Failed to convert record to GraphRelationship: %s", e)
            return None
