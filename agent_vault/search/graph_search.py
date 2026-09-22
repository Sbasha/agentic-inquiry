"""Graph search service for knowledge graph traversal and entity resolution.

Accepts StorageFacade as the storage interface. StorageFacade provides
unified access to vector and graph storage through the provider framework.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import numpy as np

from agent_vault.config import Config
from agent_vault.constants import CURRENT_PROJECT_ID
from agent_vault.database.results import SearchResult
from agent_vault.embeddings.service import EmbeddingService
from agent_vault.events import EventSystem
from agent_vault.events.context_managers import track_operation
from agent_vault.events.models import EventStatus
from agent_vault.events.types import EventTypes

if TYPE_CHECKING:
    from agent_vault.storage.facade import StorageFacade

logger = logging.getLogger(__name__)


class GraphSearchService:
    """Provides graph traversal and entity resolution capabilities.

    Requires StorageFacade as the storage interface. StorageFacade provides
    unified access to vector and graph storage through the provider framework.

    Example:
        >>> storage = await StorageFacade.from_config(config, "my_project")
        >>> graph_search = GraphSearchService(storage, config)
    """

    def __init__(
        self,
        storage: "StorageFacade",
        config: Config,
        event_system: Optional[EventSystem] = None,
        project_id: Optional[str] = None,
    ):
        """Initialize graph search service.

        Args:
            storage: StorageFacade instance providing unified storage access.
            config: Configuration object.
            event_system: Optional event system for tracking operations.
            project_id: Optional default project ID. If None, uses
                the StorageFacade's project_id.
        """
        # Store the StorageFacade - this is the primary interface for all operations
        self._storage_facade = storage

        # Extract project_id from facade if not provided
        if project_id is None:
            project_id = storage.project_id

        self.config = config
        self.event_system = event_system or EventSystem()
        self.project_id = project_id
        self._embedding_service = None

    @property
    def embedding_service(self):
        """Lazy-load embedding service. Returns None if not configured."""
        if self._embedding_service is None:
            try:
                self._embedding_service = EmbeddingService(config=self.config)
            except Exception:
                # Embedding service not configured - return None
                return None
        return self._embedding_service

    def _resolve_project_id(self, project_id: Optional[str]) -> Optional[str]:
        """Resolve project ID from parameter or instance default."""
        if project_id == CURRENT_PROJECT_ID:
            return self.project_id
        return project_id

    async def traverse_relationships(
        self,
        entity_id: str,
        relationship_types: Optional[List[str]] = None,
        direction: str = "outgoing",
        max_depth: int = 1,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
        include_metadata: bool = True,
    ) -> Dict[str, Any]:
        """Traverse relationships from an entity in the knowledge graph.

        This method implements graph traversal with support for:
        - Bidirectional traversal (outgoing, incoming, or both)
        - Relationship type filtering
        - Depth limiting
        - Relationship metadata inclusion

        Args:
            entity_id: ID of the starting entity
            relationship_types: Optional list of relationship types to filter by
            direction: Traversal direction - "outgoing", "incoming", or "both"
            max_depth: Maximum depth to traverse (1 = direct neighbors only)
            project_id: Project ID to search in (CURRENT_PROJECT_ID, specific ID, or None for all)
            include_metadata: Whether to include relationship metadata

        Returns:
            Dictionary containing:
                - entity: The starting entity
                - relationships: List of relationships organized by depth
                - entities: Map of entity_id to entity data for all discovered entities
                - depth_reached: Maximum depth actually traversed

        Example:
            >>> result = await service.traverse_relationships(
            ...     entity_id="func_123",
            ...     relationship_types=["calls", "called_by"],
            ...     direction="both",
            ...     max_depth=2
            ... )
            >>> for rel in result["relationships"]:
            ...     print(f"%s --%s--> %s", rel['source_name'], rel['type'], rel['target_name'])
        """
        # Track the operation
        async with track_operation(
            self.event_system,
            "search.traverse_relationships",
            source="GraphSearchService.traverse_relationships",
            entity_id=entity_id,
            direction=direction,
            max_depth=max_depth,
            relationship_types=relationship_types,
        ):
            try:
                # Resolve project_id
                resolved_project_id = self._resolve_project_id(project_id)

                # Validate direction
                if direction not in ["outgoing", "incoming", "both"]:
                    raise ValueError(
                        f"Invalid direction: {direction}. Must be 'outgoing', 'incoming', or 'both'"
                    )

                # Get the starting entity
                start_entities = await self._storage_facade.query_raw(
                    table_name="graph_entities",
                    filters={"id": entity_id},
                    limit=1,
                    project_id=resolved_project_id,
                )

                if not start_entities:
                    return {
                        "entity": None,
                        "relationships": [],
                        "entities": {},
                        "depth_reached": 0,
                        "error": f"Entity not found: {entity_id}",
                    }

                start_entity = start_entities[0]

                # Track all discovered entities and relationships
                all_entities = {entity_id: start_entity}
                all_relationships = []

                # Track entities at each depth level
                current_level_ids = {entity_id}
                visited_entity_ids = {entity_id}
                visited_relationship_ids = set()

                # Traverse up to max_depth
                for depth in range(1, max_depth + 1):
                    if not current_level_ids:
                        break

                    next_level_ids = set()

                    # Get outgoing relationships if requested
                    if direction in ["outgoing", "both"]:
                        filters = {"source_id": list(current_level_ids)}
                        if relationship_types:
                            filters["type"] = relationship_types

                        outgoing_rels = await self._storage_facade.query_raw(
                            table_name="graph_relationships",
                            filters=filters,
                            limit=self.config.mcp.relationships.max_per_node,
                            project_id=resolved_project_id,
                        )

                        for rel in outgoing_rels:
                            if rel["id"] not in visited_relationship_ids:
                                visited_relationship_ids.add(rel["id"])

                                # Add relationship with depth info
                                rel_info = {
                                    "id": rel["id"],
                                    "source_id": rel["source_id"],
                                    "target_id": rel["target_id"],
                                    "type": rel["type"],
                                    "depth": depth,
                                    "direction": "outgoing",
                                }

                                if include_metadata and rel.get("metadata"):
                                    rel_info["metadata"] = rel["metadata"]

                                all_relationships.append(rel_info)

                                # Track target for next level
                                target_id = rel["target_id"]
                                if target_id not in visited_entity_ids:
                                    next_level_ids.add(target_id)
                                    visited_entity_ids.add(target_id)

                    # Get incoming relationships if requested
                    if direction in ["incoming", "both"]:
                        filters = {"target_id": list(current_level_ids)}
                        if relationship_types:
                            filters["type"] = relationship_types

                        incoming_rels = await self._storage_facade.query_raw(
                            table_name="graph_relationships",
                            filters=filters,
                            limit=self.config.mcp.relationships.max_per_node,
                            project_id=resolved_project_id,
                        )

                        for rel in incoming_rels:
                            if rel["id"] not in visited_relationship_ids:
                                visited_relationship_ids.add(rel["id"])

                                # Add relationship with depth info
                                rel_info = {
                                    "id": rel["id"],
                                    "source_id": rel["source_id"],
                                    "target_id": rel["target_id"],
                                    "type": rel["type"],
                                    "depth": depth,
                                    "direction": "incoming",
                                }

                                if include_metadata and rel.get("metadata"):
                                    rel_info["metadata"] = rel["metadata"]

                                all_relationships.append(rel_info)

                                # Track source for next level
                                source_id = rel["source_id"]
                                if source_id not in visited_entity_ids:
                                    next_level_ids.add(source_id)
                                    visited_entity_ids.add(source_id)

                    # Fetch entity data for newly discovered entities
                    if next_level_ids:
                        new_entities = await self._storage_facade.query_raw(
                            table_name="graph_entities",
                            filters={"id": list(next_level_ids)},
                            limit=self.config.mcp.query.max_limit,
                            project_id=resolved_project_id,
                        )

                        for entity in new_entities:
                            all_entities[entity["id"]] = entity

                    # Move to next level
                    current_level_ids = next_level_ids

                    # If we've exhausted all paths, break early
                    if not current_level_ids:
                        depth_reached = depth
                        break
                else:
                    depth_reached = max_depth

                # Enrich relationships with entity names for easier consumption
                for rel in all_relationships:
                    source_entity = all_entities.get(rel["source_id"])
                    target_entity = all_entities.get(rel["target_id"])

                    if source_entity:
                        rel["source_name"] = source_entity["name"]
                        rel["source_type"] = source_entity["type"]

                    if target_entity:
                        rel["target_name"] = target_entity["name"]
                        rel["target_type"] = target_entity["type"]

                result = {
                    "entity": start_entity,
                    "relationships": all_relationships,
                    "entities": all_entities,
                    "depth_reached": depth_reached,
                    "total_relationships": len(all_relationships),
                    "total_entities": len(all_entities),
                }

                # Emit results event
                await self.event_system.emit(
                    EventTypes.Search.RESULTS_RETURNED,
                    source="GraphSearchService.traverse_relationships",
                    status=EventStatus.PROGRESS,
                    relationship_count=len(all_relationships),
                    entity_count=len(all_entities),
                )

                return result

            except Exception:
                # Error is automatically tracked by track_operation context manager
                raise

    async def resolve_entity(
        self,
        entity_name: str,
        entity_type: Optional[str] = None,
        context: Optional[str] = None,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
        similarity_threshold: float = 0.7,
    ) -> Dict[str, Any]:
        """Resolve an entity by name with disambiguation support.

        This method implements intelligent entity resolution with support for:
        - Qualified name resolution (e.g., "Module.Class.method")
        - Type filtering
        - Context-based disambiguation
        - Usage frequency ranking
        - Fuzzy matching for suggestions

        Args:
            entity_name: Name or qualified name of the entity to resolve
            entity_type: Optional entity type filter (from EntityType enum)
            context: Optional context string to help disambiguate
            project_id: Project ID to search in (CURRENT_PROJECT_ID, specific ID, or None for all)
            similarity_threshold: Minimum similarity score for suggestions (0.0-1.0)

        Returns:
            Dictionary containing:
                - matches: List of matching entities with disambiguation info
                - suggestions: List of similar entities if no exact matches found
                - disambiguation_needed: Boolean indicating if multiple matches exist

        Example:
            >>> result = await service.resolve_entity(
            ...     entity_name="process",
            ...     entity_type="function",
            ...     context="payment"
            ... )
            >>> if result["disambiguation_needed"]:
            ...     for match in result["matches"]:
            ...         print(f"{match['qualified_name']} in {match['file_path']}")
        """
        # Track the operation
        async with track_operation(
            self.event_system,
            "search.resolve_entity",
            source="GraphSearchService.resolve_entity",
            entity_name=entity_name,
            entity_type=entity_type,
            has_context=context is not None,
        ):
            try:
                # Resolve project_id
                resolved_project_id = self._resolve_project_id(project_id)

                # Build filters for entity search
                filters: Dict[str, Any] = {}

                # Check if entity_name is a qualified name (contains dots)
                if "." in entity_name:
                    # Qualified name: try exact match first
                    filters["name"] = entity_name
                else:
                    # Simple name: match entities ending with this name
                    # This allows matching "method" to "Class.method"
                    pass  # We'll use FTS search for flexible matching

                # Add type filter if specified
                if entity_type:
                    filters["type"] = entity_type

                # Search for entities
                if "." in entity_name:
                    # Exact qualified name search
                    matches = await self._storage_facade.query_raw(
                        table_name="graph_entities",
                        filters=filters,
                        limit=self.config.mcp.query.default_limit,
                        project_id=resolved_project_id,
                    )
                else:
                    # Flexible search using name matching
                    # Get all entities and filter by name suffix
                    all_entities = await self._storage_facade.query_raw(
                        table_name="graph_entities",
                        filters=filters if filters else {},
                        limit=self.config.mcp.query.default_limit,
                        project_id=resolved_project_id,
                    )

                    # Filter to entities whose name matches exactly or is a component
                    # Match if:
                    # 1. Name equals entity_name exactly
                    # 2. Name ends with ".entity_name" (qualified name component)
                    matches = [
                        e
                        for e in all_entities
                        if (e["name"] == entity_name or e["name"].endswith("." + entity_name))
                    ]

                # Apply context-based filtering if provided (requires embeddings)
                if context and matches and self.embedding_service is not None:
                    # Use embeddings to find entities most relevant to context
                    context_vector = await self.embedding_service.embed_async(context)

                    # Calculate similarity between context and each entity
                    for match in matches:
                        entity_vector = match.get("vector", [])
                        if entity_vector:
                            similarity = np.dot(context_vector, entity_vector) / (
                                np.linalg.norm(context_vector) * np.linalg.norm(entity_vector)
                            )
                            match["context_similarity"] = float(similarity)
                        else:
                            match["context_similarity"] = 0.0

                    # Sort by context similarity
                    matches.sort(key=lambda x: x.get("context_similarity", 0.0), reverse=True)

                # Rank by usage frequency (using pagerank if available)
                for match in matches:
                    match["usage_score"] = match.get("pagerank", 0.0)

                # Sort by usage score if no context filtering was applied
                if not context:
                    matches.sort(key=lambda x: x.get("usage_score", 0.0), reverse=True)

                # Build disambiguation info for each match
                disambiguated_matches = []
                for match in matches:
                    disambiguated_matches.append(
                        {
                            "id": match["id"],
                            "name": match["name"],
                            "qualified_name": match["name"],  # Already qualified in graph
                            "type": match["type"],
                            "file_path": match.get("file_path", ""),
                            "doc_id": match["doc_id"],
                            "usage_score": match.get("usage_score", 0.0),
                            "context_similarity": match.get("context_similarity"),
                            "location": {
                                "file": match.get("file_path", ""),
                                "project_id": match.get("project_id", ""),
                            },
                        }
                    )

                # If no matches found, generate suggestions using fuzzy matching
                suggestions = []
                if not disambiguated_matches and self.embedding_service is not None:
                    # Use vector search to find similar entities
                    query_vector_array = await self.embedding_service.embed_async(entity_name)
                    query_vector = query_vector_array.tolist()  # Convert numpy array to list

                    similar_entities = await self._storage_facade.vector_search_raw(
                        table="graph_entities",
                        vector=query_vector,
                        vector_column="vector",
                        limit=10,  # Keep small for suggestions
                        filters={"type": entity_type} if entity_type else {},
                        project_id=resolved_project_id,
                    )

                    # Filter by similarity threshold
                    for entity in similar_entities:
                        # LanceDB returns _distance, lower is better
                        # Convert to similarity score (0-1, higher is better)
                        distance = entity.get("_distance", 1.0)
                        similarity = max(0.0, 1.0 - distance)

                        if similarity >= similarity_threshold:
                            suggestions.append(
                                {
                                    "name": entity["name"],
                                    "type": entity["type"],
                                    "file_path": entity.get("file_path", ""),
                                    "similarity_score": similarity,
                                }
                            )

                result = {
                    "matches": disambiguated_matches,
                    "suggestions": suggestions,
                    "disambiguation_needed": len(disambiguated_matches) > 1,
                    "found": bool(disambiguated_matches),
                }

                # Emit results event
                await self.event_system.emit(
                    EventTypes.Search.RESULTS_RETURNED,
                    source="GraphSearchService.resolve_entity",
                    status=EventStatus.PROGRESS,
                    match_count=len(disambiguated_matches),
                    suggestion_count=len(suggestions),
                )

                return result

            except Exception:
                # Error is automatically tracked by track_operation context manager
                raise

    async def enrich_with_graph_context(
        self,
        search_results: List[Dict[str, Any]],
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[Dict[str, Any]]:
        """Enrich search results with graph context.

        Args:
            search_results: List of search results to enrich
            project_id: Project ID to filter graph entities by

        Returns:
            Search results enriched with graph context
        """
        doc_ids = [result["doc_id"] for result in search_results]
        if not doc_ids:
            return search_results

        # Resolve project_id
        resolved_project_id = self._resolve_project_id(project_id)

        graph_entities = await self._storage_facade.query_raw(
            table_name="graph_entities",
            filters={"doc_id": doc_ids},
            project_id=resolved_project_id,
        )

        entities_by_doc: Dict[str, List[Dict[str, Any]]] = {}
        for entity in graph_entities:
            entities_by_doc.setdefault(entity["doc_id"], []).append(entity)

        for result in search_results:
            entities = entities_by_doc.get(result["doc_id"])
            if entities:
                result["graph_context"] = entities

        return search_results

    async def _graph_ranking_supported(self) -> bool:
        """Check if graph ranking is supported."""
        try:
            # Check if graph tables exist
            tables = await self._storage_facade.list_tables()
            return "graph_entities" in tables and "graph_relationships" in tables
        except Exception as e:
            logger.warning("Failed to check graph ranking support: %s", e)
            return False

    async def graph_filtered_search(
        self,
        graph_filters: Dict[str, Any],
        search_query_vector: Optional[List[float]] = None,
        search_query_fts: Optional[str] = None,
        hybrid_search_fn: Optional[Any] = None,
        vector_search_fn: Optional[Any] = None,
        limit: Optional[int] = None,
        depth: Optional[int] = None,
        vector_column_name: str = "vector",
        project_id: Optional[str] = CURRENT_PROJECT_ID,
        project_ids: Optional[List[str]] = None,
    ) -> Union[List[Dict[str, Any]], List[SearchResult]]:
        """Perform graph-filtered search.

        Finds entities matching `graph_filters`, traverses `depth` levels
        of the graph to find related entities, and then performs a
        vector/hybrid search within that expanded set of entities.

        Args:
            graph_filters: Filters to find starting entities for traversal.
            search_query_vector: Optional query vector for final search.
            search_query_fts: Optional FTS query for final search.
            hybrid_search_fn: Function to call for hybrid search.
            vector_search_fn: Function to call for vector search.
            limit: Maximum results to return.
            depth: Graph traversal depth.
            vector_column_name: Name of vector column.
            project_id: Project to search within.
            project_ids: List of projects for multi-project search.

        Returns:
            List of search results as dicts or SearchResult objects.
        """
        # Track the search operation
        async with track_operation(
            self.event_system,
            "search.query",
            source="GraphSearchService.graph_filtered_search",
            search_type="graph_filtered",
            limit=limit,
            depth=depth,
            project_id=project_id,
            project_ids=project_ids,
        ):
            try:
                if limit is None:
                    limit = self.config.search.default_limit
                if depth is None:
                    depth = self.config.search.graph_search.max_depth
                    
                if not await self._graph_ranking_supported():
                    # Fallback to regular search
                    if search_query_vector is not None and search_query_fts is not None and hybrid_search_fn:
                        results = await hybrid_search_fn(
                            query_vector=search_query_vector,
                            query_fts=search_query_fts,
                            limit=limit,
                            rerank_by_graph=False,
                            vector_column_name=vector_column_name,
                            project_id=project_id,
                            project_ids=project_ids,
                        )
                    elif search_query_vector is not None and vector_search_fn:
                        results = await vector_search_fn(
                            query_vector=search_query_vector,
                            limit=limit,
                            vector_column_name=vector_column_name,
                            project_id=project_id,
                        )
                    else:
                        results = []

                    # Emit results event
                    await self.event_system.emit(
                        EventTypes.Search.RESULTS_RETURNED,
                        source="GraphSearchService.graph_filtered_search",
                        status=EventStatus.PROGRESS,
                        result_count=len(results),
                        search_type="graph_filtered_fallback",
                    )

                    return results

                # Handle multi-project search
                if project_ids is not None:
                    results = await self._graph_filtered_search_multi_project(
                        graph_filters=graph_filters,
                        search_query_vector=search_query_vector,
                        search_query_fts=search_query_fts,
                        hybrid_search_fn=hybrid_search_fn,
                        limit=limit,
                        depth=depth,
                        vector_column_name=vector_column_name,
                        project_ids=project_ids,
                    )

                    # Emit results event
                    await self.event_system.emit(
                        EventTypes.Search.RESULTS_RETURNED,
                        source="GraphSearchService.graph_filtered_search",
                        status=EventStatus.PROGRESS,
                        result_count=len(results),
                        search_type="graph_filtered_multi_project",
                    )

                    return results

                # Resolve project_id
                resolved_project_id = self._resolve_project_id(project_id)

                start_entities = await self._storage_facade.query_raw(
                    table_name="graph_entities",
                    filters=graph_filters,
                    project_id=resolved_project_id,
                )
                all_entity_ids = {entity["id"] for entity in start_entities}
                current_ids = set(all_entity_ids)

                for _ in range(depth):
                    if not current_ids:
                        break
                    relationships = await self._storage_facade.query_raw(
                        table_name="graph_relationships",
                        filters={"source_id": list(current_ids)},
                        limit=self.config.mcp.relationships.max_per_node,
                        project_id=resolved_project_id,
                    )
                    target_ids = {relationship["target_id"] for relationship in relationships}
                    new_ids = target_ids - all_entity_ids
                    if not new_ids:
                        break
                    all_entity_ids.update(new_ids)
                    current_ids = new_ids

                if not all_entity_ids:
                    # Emit results event for empty results
                    await self.event_system.emit(
                        EventTypes.Search.RESULTS_RETURNED,
                        source="GraphSearchService.graph_filtered_search",
                        status=EventStatus.PROGRESS,
                        result_count=0,
                        search_type="graph_filtered",
                    )
                    return []

                final_entities = await self._storage_facade.query_raw(
                    table_name="graph_entities",
                    filters={"id": list(all_entity_ids)},
                    project_id=resolved_project_id,
                )
                doc_ids = {entity["doc_id"] for entity in final_entities}
                if not doc_ids:
                    # Emit results event for empty results
                    await self.event_system.emit(
                        EventTypes.Search.RESULTS_RETURNED,
                        source="GraphSearchService.graph_filtered_search",
                        status=EventStatus.PROGRESS,
                        result_count=0,
                        search_type="graph_filtered",
                    )
                    return []

                chunk_filters = {"doc_id": list(doc_ids)}

                if search_query_vector is not None and search_query_fts is not None and hybrid_search_fn:
                    results = await hybrid_search_fn(
                        query_vector=search_query_vector,
                        query_fts=search_query_fts,
                        filters=chunk_filters,
                        limit=limit,
                        vector_column_name=vector_column_name,
                        project_id=resolved_project_id,
                    )
                elif search_query_vector is not None and vector_search_fn:
                    results = await vector_search_fn(
                        query_vector=search_query_vector,
                        limit=limit,
                        filters=chunk_filters,
                        vector_column_name=vector_column_name,
                        project_id=resolved_project_id,
                    )
                else:
                    results = await self._storage_facade.query_raw(
                        table_name="document_chunks",
                        filters=chunk_filters,
                        limit=limit,
                        project_id=resolved_project_id,
                    )

                # Emit results event
                await self.event_system.emit(
                    EventTypes.Search.RESULTS_RETURNED,
                    source="GraphSearchService.graph_filtered_search",
                    status=EventStatus.PROGRESS,
                    result_count=len(results),
                    search_type="graph_filtered",
                )

                return results
            except Exception:
                # Error is automatically tracked by track_operation context manager
                raise

    async def _graph_filtered_search_multi_project(
        self,
        graph_filters: Dict[str, Any],
        search_query_vector: Optional[List[float]],
        search_query_fts: Optional[str],
        hybrid_search_fn,
        limit: int,
        depth: int,
        vector_column_name: str,
        project_ids: List[str],
    ) -> List[Dict[str, Any]]:
        """Perform graph-filtered search across multiple projects."""
        # Get starting entities across all projects
        start_entities = await self._storage_facade.query_across_projects(
            table_name="graph_entities",
            project_ids=project_ids,
            filters=graph_filters,
        )

        all_entity_ids = {entity["id"] for entity in start_entities}
        current_ids = set(all_entity_ids)

        # Traverse graph across all projects
        for _ in range(depth):
            if not current_ids:
                break
            relationships = await self._storage_facade.query_across_projects(
                table_name="graph_relationships",
                project_ids=project_ids,
                filters={"source_id": list(current_ids)},
                limit=self.config.mcp.relationships.max_per_node,
            )
            target_ids = {relationship["target_id"] for relationship in relationships}
            new_ids = target_ids - all_entity_ids
            if not new_ids:
                break
            all_entity_ids.update(new_ids)
            current_ids = new_ids

        if not all_entity_ids:
            return []

        # Get final entities
        final_entities = await self._storage_facade.query_across_projects(
            table_name="graph_entities",
            project_ids=project_ids,
            filters={"id": list(all_entity_ids)},
        )

        doc_ids = {entity["doc_id"] for entity in final_entities}
        if not doc_ids:
            return []

        chunk_filters = {"doc_id": list(doc_ids)}

        # Perform search with filters
        if search_query_vector is not None and search_query_fts is not None and hybrid_search_fn:
            return await hybrid_search_fn(
                query_vector=search_query_vector,
                query_fts=search_query_fts,
                limit=limit,
                filters=chunk_filters,
                rerank_by_graph=False,
                vector_column_name=vector_column_name,
                project_ids=project_ids,
            )

        if search_query_vector is not None:
            results = await self._storage_facade.query_across_projects(
                table_name="document_chunks",
                project_ids=project_ids,
                filters=chunk_filters,
                limit=limit,
            )
            return self._enrich_results_with_project_id(results)

        results = await self._storage_facade.query_across_projects(
            table_name="document_chunks",
            project_ids=project_ids,
            filters=chunk_filters,
            limit=limit,
        )
        return self._enrich_results_with_project_id(results)

    def _enrich_results_with_project_id(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Enrich results with project_id field."""
        for result in results:
            if "project_id" not in result:
                result["project_id"] = result.get("_project_id", "unknown")
        return results

    async def rerank_by_graph(self, search_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Rerank search results by graph pagerank scores."""
        enriched_results = await self.enrich_with_graph_context(search_results)

        def best_pagerank(result: Dict[str, Any]) -> float:
            context = result.get("graph_context", {})
            entities = context.get("entities", [])
            if not entities:
                return 0.0
            return max(entity.get("pagerank", 0.0) for entity in entities)

        return sorted(enriched_results, key=best_pagerank, reverse=True)
