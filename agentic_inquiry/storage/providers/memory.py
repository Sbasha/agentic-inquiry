"""In-memory storage provider for testing.

This module provides the InMemoryProvider class that implements
storage protocols using in-memory data structures. This is useful
for testing and development without external dependencies.
"""

from __future__ import annotations

import logging
import math
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Dict,
    List,
    Optional,
    Sequence,
    Union,
)

from agentic_inquiry.database.results import SearchResult
from agentic_inquiry.models.document_chunk import DocumentChunk
from agentic_inquiry.models.graph_entity import GraphEntity
from agentic_inquiry.models.graph_relationship import GraphRelationship

if TYPE_CHECKING:
    from agentic_inquiry.config import Config
    from agentic_inquiry.database.filters import FilterInput

logger = logging.getLogger(__name__)


def _compile_predicate(
    filters: "Optional[FilterInput]",
) -> Callable[[Dict[str, Any]], bool]:
    """Compile filter input into a predicate over row dicts, once.

    The provider scans items in tight loops — rebuilding the
    :class:`MemoryFilterAdapter` predicate per row would walk the AST and
    recompile any LIKE regex on every comparison. Callers build the
    predicate once via this helper, then apply it in the loop.

    Returns a ``lambda _: True`` no-op for ``None``/empty filters so the
    callsite can unconditionally call the predicate.
    """
    from agentic_inquiry.database.filters import MemoryFilterAdapter

    if not filters:
        return lambda _row: True
    compiled = MemoryFilterAdapter().translate(filters)
    if compiled is None:
        return lambda _row: True
    return compiled


def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(vec1) != len(vec2):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))

    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0

    return dot_product / (norm1 * norm2)


def _matches_filters(item: Dict[str, Any], filters: "Optional[FilterInput]") -> bool:
    """Check whether ``item`` matches all conditions in ``filters``.

    Convenience wrapper that compiles the predicate on each call — cheap
    enough for one-shot assertions in tests. Provider methods that scan
    large collections should call :func:`_compile_predicate` once outside
    the loop instead.

    Supports the same operator set as Postgres/LanceDB via
    :class:`agentic_inquiry.database.filters.MemoryFilterAdapter`: IN,
    NOT_IN, IS_NULL, IS_NOT_NULL, comparison (>, >=, <, <=), LIKE/ILIKE,
    and nested AND/OR via the ``OR``/``NOT`` dict keys.
    """
    return _compile_predicate(filters)(item)


class InMemoryProvider:
    """In-memory implementation of storage protocols for testing.

    This provider implements:
    - VectorStorageProtocol: Vector search using brute-force cosine similarity
    - GraphStorageProtocol: Knowledge graph with dict storage
    - MaintenanceProtocol: No-op maintenance operations

    This provider is NOT suitable for production use. Use LanceDBProvider
    for production workloads.

    Example:
        provider = await InMemoryProvider.from_config(config, "test_project")
        await provider.initialize()

        await provider.upsert_chunks(chunks, "test_project")
        results = await provider.vector_search(query_vector, limit=10)

    Attributes:
        SUPPORTED_ROLES: Storage roles this provider supports
        project_id: Project ID for data isolation
        _chunks: In-memory chunk storage (id -> chunk dict)
        _entities: In-memory entity storage (id -> entity dict)
        _relationships: In-memory relationship storage (id -> relationship dict)
    """

    SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset({"vector", "graph"})

    def __init__(
        self,
        config: Optional["Config"] = None,
        project_id: str = "default",
    ) -> None:
        """Initialize in-memory provider."""
        self._config = config
        self._project_id = project_id

        # In-memory storage
        # Key: (chunk_id, project_id) -> chunk_dict
        self._chunks: Dict[tuple[str, str], Dict[str, Any]] = {}
        # Key: (entity_id, project_id) -> entity_dict
        self._entities: Dict[tuple[str, str], Dict[str, Any]] = {}
        # Key: (rel_id, project_id) -> rel_dict
        self._relationships: Dict[tuple[str, str], Dict[str, Any]] = {}

        self._initialized = False

    @classmethod
    async def from_config(
        cls,
        config: "Config",
        project_id: str,
    ) -> "InMemoryProvider":
        """Create provider from configuration.

        Args:
            config: Configuration instance
            project_id: Project ID for data isolation

        Returns:
            Configured InMemoryProvider instance
        """
        provider = cls(config, project_id)
        await provider.initialize()
        return provider

    # =========================================================================
    # Lifecycle Methods
    # =========================================================================

    async def initialize(self) -> None:
        """Initialize the storage backend.

        For in-memory provider, this is a no-op.
        """
        if self._initialized:
            return

        logger.info("Initializing in-memory provider for project %s", self._project_id)
        self._initialized = True

    async def close(self) -> None:
        """Close the storage backend.

        Clears all in-memory data.
        """
        if not self._initialized:
            return

        logger.info("Closing in-memory provider for project %s", self._project_id)
        self._chunks.clear()
        self._entities.clear()
        self._relationships.clear()
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        """Check if the provider is initialized."""
        return self._initialized

    # =========================================================================
    # VectorStorageProtocol Implementation
    # =========================================================================

    async def upsert_chunks(
        self,
        chunks: Sequence[DocumentChunk],
        project_id: str,
    ) -> int:
        """Insert or update document chunks."""
        count = 0
        for chunk in chunks:
            chunk_dict = chunk.to_dict()
            # Use composite key (chunk_id, project_id)
            key = (chunk.id, project_id)
            self._chunks[key] = chunk_dict
            count += 1
        return count

    async def delete_chunks_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> int:
        """Delete all chunks from a specific file."""
        # Keys are now (chunk_id, project_id) tuples
        to_delete = [
            key
            for key, chunk in self._chunks.items()
            if chunk.get("file_path") == file_path
            and chunk.get("project_id") == project_id
        ]
        for key in to_delete:
            del self._chunks[key]
        return len(to_delete)

    async def delete_chunks_by_ids(
        self,
        chunk_ids: List[str],
        project_id: str,
    ) -> int:
        """Delete chunks by their IDs."""
        count = 0
        for chunk_id in chunk_ids:
            key = (chunk_id, project_id)
            if key in self._chunks:
                del self._chunks[key]
                count += 1
        return count

    async def get_chunks_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> List[DocumentChunk]:
        """Get all chunks from a specific file."""
        results = []
        for chunk_dict in self._chunks.values():
            if (
                chunk_dict.get("file_path") == file_path
                and chunk_dict.get("project_id") == project_id
            ):
                results.append(self._dict_to_chunk(chunk_dict))
        return results

    async def vector_search(
        self,
        query_vector: List[float],
        limit: int = 10,
        filters: "Optional[FilterInput]" = None,
        project_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Search for similar documents by vector using brute-force cosine similarity."""
        candidates = []
        target_project_id = project_id or self._project_id
        predicate = _compile_predicate(filters)

        for key, chunk_dict in self._chunks.items():
            # Key is (chunk_id, project_id)
            chunk_id_val, chunk_project_id = key

            # Apply project filter
            if target_project_id and chunk_project_id != target_project_id:
                continue

            # Apply additional filters
            if not predicate(chunk_dict):
                continue

            # Compute cosine similarity
            chunk_vector = chunk_dict.get("vector", [])
            if not chunk_vector:
                continue

            similarity = _cosine_similarity(query_vector, chunk_vector)
            candidates.append((chunk_id_val, chunk_dict, similarity))

        # Sort by similarity descending
        candidates.sort(key=lambda x: x[2], reverse=True)

        # Return top results
        results = []
        for chunk_id, chunk_dict, similarity in candidates[:limit]:
            # Normalize similarity to 0-1 range (cosine similarity is already -1 to 1)
            score = max(0.0, min(1.0, (similarity + 1.0) / 2.0))
            results.append(
                SearchResult(
                    id=chunk_id,
                    data=chunk_dict,
                    score=score,
                    source="vector",
                )
            )
        return results

    async def fts_search(
        self,
        query: str,
        limit: int = 10,
        filters: "Optional[FilterInput]" = None,
        project_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Search using simple text matching."""
        candidates = []
        query_lower = query.lower()
        query_terms = query_lower.split()
        target_project_id = project_id or self._project_id
        predicate = _compile_predicate(filters)

        for key, chunk_dict in self._chunks.items():
            # Key is (chunk_id, project_id)
            chunk_id_val, chunk_project_id = key

            # Apply project filter
            if target_project_id and chunk_project_id != target_project_id:
                continue

            # Apply additional filters
            if not predicate(chunk_dict):
                continue

            # Simple term matching on fts_text and content
            fts_text = str(chunk_dict.get("fts_text", "")).lower()
            content = str(chunk_dict.get("content", "")).lower()
            combined_text = f"{fts_text} {content}"

            # Count matching terms
            matches = sum(1 for term in query_terms if term in combined_text)
            if matches > 0:
                score = min(1.0, matches / len(query_terms))
                candidates.append((chunk_id_val, chunk_dict, score))

        # Sort by score descending
        candidates.sort(key=lambda x: x[2], reverse=True)

        # Return top results
        results = []
        for chunk_id, chunk_dict, score in candidates[:limit]:
            results.append(
                SearchResult(
                    id=chunk_id,
                    data=chunk_dict,
                    score=score,
                    source="fts",
                )
            )
        return results

    async def hybrid_search(
        self,
        query_vector: List[float],
        query_text: str,
        limit: int = 10,
        vector_weight: float = 0.7,
        project_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Search using both vector similarity and text matching."""
        # Get more results from both searches for better fusion
        fetch_limit = limit * 3

        vector_results = await self.vector_search(
            query_vector, fetch_limit, project_id=project_id
        )
        fts_results = await self.fts_search(
            query_text, fetch_limit, project_id=project_id
        )

        # Simple score fusion
        score_map: Dict[str, float] = {}
        data_map: Dict[str, Dict[str, Any]] = {}

        fts_weight = 1.0 - vector_weight

        for result in vector_results:
            score_map[result.id] = result.score * vector_weight
            data_map[result.id] = result.data

        for result in fts_results:
            if result.id in score_map:
                score_map[result.id] += result.score * fts_weight
            else:
                score_map[result.id] = result.score * fts_weight
                data_map[result.id] = result.data

        # Sort and return top results
        sorted_ids = sorted(score_map.keys(), key=lambda x: score_map[x], reverse=True)

        results = []
        for result_id in sorted_ids[:limit]:
            results.append(
                SearchResult(
                    id=result_id,
                    data=data_map[result_id],
                    score=min(1.0, score_map[result_id]),
                    source="hybrid",
                )
            )
        return results

    async def query(
        self,
        filters: "FilterInput",
        limit: int = 100,
        offset: int = 0,
        project_id: Optional[str] = None,
    ) -> List[DocumentChunk]:
        """Query chunks with filters."""
        results = []
        predicate = _compile_predicate(filters)
        for chunk_dict in self._chunks.values():
            if project_id and chunk_dict.get("project_id") != project_id:
                continue
            if predicate(chunk_dict):
                results.append(self._dict_to_chunk(chunk_dict))

        return results[offset : offset + limit]

    async def count(
        self,
        filters: "Optional[FilterInput]" = None,
        project_id: Optional[str] = None,
    ) -> int:
        """Count chunks matching filters."""
        count = 0
        predicate = _compile_predicate(filters)
        for chunk_dict in self._chunks.values():
            if project_id and chunk_dict.get("project_id") != project_id:
                continue
            if predicate(chunk_dict):
                count += 1
        return count

    async def entity_vector_search(
        self,
        query_vector: Union[str, List[float]],
        project_id: str,
        limit: int = 50,
        entity_type: Optional[str] = None,
    ) -> List[GraphEntity]:
        """Brute-force cosine similarity over the stored entity vectors.

        Test/dev-only provider, so a full table scan is fine. Entities
        without a stored vector, or with a mismatched dim, are skipped —
        mirrors LanceDB/Postgres behaviour (no match rather than raise).

        No server-side embedding: a raw ``str`` query would fall through
        to a ``len(query_vector)`` comparison that's semantically wrong
        (character count vs vector dim). Reject it explicitly per the
        protocol's "SHOULD raise for str input" clause.
        """
        if isinstance(query_vector, str):
            raise TypeError(
                "InMemoryProvider does not support server-side embedding; "
                "entity_vector_search requires a list of floats, got str."
            )
        candidates: list[tuple[float, Dict[str, Any]]] = []
        for (_entity_id, entity_project_id), entity_dict in self._entities.items():
            if entity_project_id != project_id:
                continue
            if entity_type and entity_dict.get("type") != entity_type:
                continue
            vector = entity_dict.get("vector") or []
            if not vector or len(vector) != len(query_vector):
                continue
            similarity = _cosine_similarity(query_vector, vector)
            # pgvector/LanceDB return distance; emulate by using (1 - cos)
            # so smaller is closer and callers get consistent ordering.
            distance = 1.0 - similarity
            candidates.append((distance, entity_dict))

        candidates.sort(key=lambda pair: pair[0])

        results: List[GraphEntity] = []
        for distance, entity_dict in candidates[:limit]:
            entity = self._dict_to_entity(entity_dict)
            entity._distance = distance
            results.append(entity)
        return results

    async def query_across_projects(
        self,
        table_name: str,
        project_ids: Sequence[str],
        filters: "Optional[FilterInput]" = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query data across multiple projects."""
        # Map table name to internal storage
        if table_name == "document_chunks":
            storage = self._chunks
        elif table_name == "graph_entities":
            storage = self._entities
        elif table_name == "graph_relationships":
            storage = self._relationships
        else:
            return []

        results = []
        project_ids_set = set(project_ids)
        predicate = _compile_predicate(filters)

        for item_dict in storage.values():
            # Check project_id is in the set
            if item_dict.get("project_id") not in project_ids_set:
                continue
            # Apply filters if any
            if predicate(item_dict):
                results.append(item_dict)
                if len(results) >= limit:
                    break

        return results

    async def list_tables(self) -> List[str]:
        """List all tables in the storage."""
        return ["document_chunks", "graph_entities", "graph_relationships"]

    async def table_exists(self, table_name: str) -> bool:
        """Check if a table exists."""
        return table_name in await self.list_tables()

    # =========================================================================
    # GraphStorageProtocol Implementation
    # =========================================================================

    async def upsert_entities(
        self,
        entities: Sequence[GraphEntity],
        project_id: str,
    ) -> int:
        """Insert or update graph entities."""
        count = 0
        for entity in entities:
            entity_dict = entity.to_dict()
            # Use composite key (entity_id, project_id) for proper project isolation
            key = (entity.id, entity.project_id)
            self._entities[key] = entity_dict
            count += 1
        return count

    async def get_entity(
        self,
        entity_id: str,
        project_id: str,
    ) -> Optional[GraphEntity]:
        """Retrieve an entity by ID."""
        # Use composite key (entity_id, project_id) for lookup
        key = (entity_id, project_id)
        entity_dict = self._entities.get(key)
        if entity_dict:
            return self._dict_to_entity(entity_dict)
        return None

    async def get_entities_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> List[GraphEntity]:
        """Get all entities from a specific file."""
        results = []
        for entity_dict in self._entities.values():
            if (
                entity_dict.get("file_path") == file_path
                and entity_dict.get("project_id") == project_id
            ):
                results.append(self._dict_to_entity(entity_dict))
        return results

    async def get_entities_by_type(
        self,
        entity_type: str,
        project_id: str,
        limit: int = 100,
    ) -> List[GraphEntity]:
        """Get entities by type."""
        results = []
        for entity_dict in self._entities.values():
            if (
                entity_dict.get("type") == entity_type
                and entity_dict.get("project_id") == project_id
            ):
                results.append(self._dict_to_entity(entity_dict))
                if len(results) >= limit:
                    break
        return results

    async def delete_entities_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> int:
        """Delete all entities from a specific file."""
        # Keys are now (entity_id, project_id) tuples
        to_delete = [
            key
            for key, entity in self._entities.items()
            if entity.get("file_path") == file_path
            and entity.get("project_id") == project_id
        ]
        for key in to_delete:
            del self._entities[key]
        return len(to_delete)

    async def delete_entities_by_ids(
        self,
        entity_ids: List[str],
        project_id: str,
    ) -> int:
        """Delete entities by their IDs.

        Also cascade deletes relationships where deleted entities are
        source or target, respecting project isolation.
        """
        count = 0
        entity_ids_set = set(entity_ids)

        for entity_id in entity_ids:
            # Use composite key for lookup
            key = (entity_id, project_id)
            if key in self._entities:
                del self._entities[key]
                count += 1

        # Cascade delete relationships involving deleted entities
        # Only delete relationships in the same project
        to_delete = []
        for key, rel in self._relationships.items():
            # key is (rel_id, proj_id)
            _, rel_project_id = key

            if rel_project_id != project_id:
                continue

            if (
                rel.get("source_id") in entity_ids_set
                or rel.get("target_id") in entity_ids_set
            ):
                to_delete.append(key)

        for key in to_delete:
            del self._relationships[key]

        return count

    async def query_entities(
        self,
        filters: "FilterInput",
        project_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GraphEntity]:
        """Query entities with filters."""
        results = []
        predicate = _compile_predicate(filters)
        for entity_dict in self._entities.values():
            if entity_dict.get("project_id") != project_id:
                continue
            if predicate(entity_dict):
                results.append(self._dict_to_entity(entity_dict))

        return results[offset : offset + limit]

    async def count_entities(
        self,
        filters: "Optional[FilterInput]" = None,
        project_id: Optional[str] = None,
    ) -> int:
        """Count entities matching filters."""
        count = 0
        predicate = _compile_predicate(filters)
        for entity_dict in self._entities.values():
            if project_id and entity_dict.get("project_id") != project_id:
                continue
            if predicate(entity_dict):
                count += 1
        return count

    async def upsert_relationships(
        self,
        relationships: Sequence[GraphRelationship],
        project_id: str,
    ) -> int:
        """Insert or update graph relationships."""
        count = 0
        for rel in relationships:
            rel_dict = rel.to_dict()
            # Use composite key (rel_id, project_id) for proper project isolation
            key = (rel.id, rel.project_id)
            self._relationships[key] = rel_dict
            count += 1
        return count

    async def get_relationships_by_entity(
        self,
        entity_id: str,
        direction: str = "both",
        relationship_types: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> List[GraphRelationship]:
        """Get relationships for an entity."""
        results = []
        for rel_dict in self._relationships.values():
            if project_id and rel_dict.get("project_id") != project_id:
                continue

            # Check direction
            is_source = rel_dict.get("source_id") == entity_id
            is_target = rel_dict.get("target_id") == entity_id

            if direction == "outgoing" and not is_source:
                continue
            if direction == "incoming" and not is_target:
                continue
            if direction == "both" and not (is_source or is_target):
                continue

            # Check relationship types
            if relationship_types and rel_dict.get("type") not in relationship_types:
                continue

            results.append(self._dict_to_relationship(rel_dict))

        return results

    async def count_relationships_by_type(
        self,
        project_id: str,
    ) -> Dict[str, int]:
        """Count relationships grouped by relationship type."""
        counts: Dict[str, int] = {}
        for rel_dict in self._relationships.values():
            if rel_dict.get("project_id") != project_id:
                continue
            rel_type = rel_dict.get("type", "unknown")
            counts[rel_type] = counts.get(rel_type, 0) + 1
        return counts

    async def delete_relationships_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> int:
        """Delete all relationships from a specific file.

        Deletes relationships where entities from this file are source or target.
        """
        # Get entity IDs from this file
        file_entity_ids = {
            key[0]  # Extract ID from composite key (id, proj)
            for key, entity in self._entities.items()
            if entity.get("file_path") == file_path
            and entity.get("project_id") == project_id
        }

        to_delete = [
            key
            for key, rel in self._relationships.items()
            if (
                rel.get("source_id") in file_entity_ids
                or rel.get("target_id") in file_entity_ids
            )
            and rel.get("project_id") == project_id
        ]

        for key in to_delete:
            del self._relationships[key]
        return len(to_delete)

    async def delete_relationships_by_entity(
        self,
        entity_id: str,
        project_id: str,
    ) -> int:
        """Delete all relationships for an entity."""
        to_delete = [
            key
            for key, rel in self._relationships.items()
            if (rel.get("source_id") == entity_id or rel.get("target_id") == entity_id)
            and rel.get("project_id") == project_id
        ]

        for key in to_delete:
            del self._relationships[key]
        return len(to_delete)

    async def delete_relationships_by_ids(
        self,
        relationship_ids: Sequence[str],
        project_id: str,
    ) -> int:
        """Delete relationships by their IDs."""
        deleted = 0
        for rel_id in relationship_ids:
            # Use composite key
            key = (rel_id, project_id)
            if key in self._relationships:
                del self._relationships[key]
                deleted += 1
        return deleted

    async def query_relationships(
        self,
        filters: "FilterInput",
        project_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GraphRelationship]:
        """Query relationships with filters."""
        results = []
        predicate = _compile_predicate(filters)
        for rel_dict in self._relationships.values():
            if rel_dict.get("project_id") != project_id:
                continue
            if predicate(rel_dict):
                results.append(self._dict_to_relationship(rel_dict))

        return results[offset : offset + limit]

    async def get_neighbors(
        self,
        entity_id: str,
        direction: str = "both",
        depth: int = 1,
        relationship_types: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> List[GraphEntity]:
        """Get neighboring entities using BFS."""
        visited: set[str] = {entity_id}
        current_level: set[str] = {entity_id}

        for _ in range(depth):
            next_level: set[str] = set()

            for current_id in current_level:
                rels = await self.get_relationships_by_entity(
                    current_id, direction, relationship_types, project_id
                )

                for rel in rels:
                    # Get the other entity in the relationship
                    other_id = (
                        rel.target_id if rel.source_id == current_id else rel.source_id
                    )
                    if other_id not in visited:
                        visited.add(other_id)
                        next_level.add(other_id)

            current_level = next_level
            if not current_level:
                break

        # Get entity objects for all neighbors (excluding start entity)
        visited.discard(entity_id)
        results = []
        for neighbor_id in visited:
            entity = await self.get_entity(neighbor_id, project_id or self._project_id)
            if entity:
                results.append(entity)

        return results

    async def traverse(
        self,
        start_entity_id: str,
        max_depth: int = 2,
        relationship_types: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Traverse the graph from a starting entity."""
        visited_entities: Dict[str, GraphEntity] = {}
        visited_relationships: Dict[str, GraphRelationship] = {}
        depth_reached = 0

        # Get start entity
        start_entity = await self.get_entity(
            start_entity_id, project_id or self._project_id
        )
        if start_entity:
            visited_entities[start_entity_id] = start_entity

        # BFS traversal
        current_level: set[str] = {start_entity_id}

        for current_depth in range(max_depth):
            next_level: set[str] = set()

            for current_id in current_level:
                rels = await self.get_relationships_by_entity(
                    current_id, "both", relationship_types, project_id
                )

                for rel in rels:
                    visited_relationships[rel.id] = rel

                    # Get the other entity
                    other_id = (
                        rel.target_id if rel.source_id == current_id else rel.source_id
                    )

                    if other_id not in visited_entities:
                        entity = await self.get_entity(
                            other_id, project_id or self._project_id
                        )
                        if entity:
                            visited_entities[other_id] = entity
                            next_level.add(other_id)

            if next_level:
                depth_reached = current_depth + 1
            current_level = next_level
            if not current_level:
                break

        return {
            "entities": list(visited_entities.values()),
            "relationships": list(visited_relationships.values()),
            "start_entity": start_entity,
            "depth_reached": depth_reached,
        }

    # =========================================================================
    # MaintenanceProtocol Implementation (no-ops for in-memory)
    # =========================================================================

    async def health_check(self) -> Dict[str, Any]:
        """Check storage health."""
        return {
            "status": "healthy",
            "latency_ms": 0,
            "table_count": 3,
        }

    async def run_maintenance(
        self,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """No-op for in-memory provider."""
        return {
            "summary": "No maintenance needed for in-memory storage",
            "fragments_reduced": 0,
            "bytes_reclaimed": 0,
            "duration_ms": 0,
            "tables_processed": [],
        }

    async def compact(
        self,
        project_id: Optional[str] = None,
    ) -> None:
        """No-op for in-memory provider."""
        pass

    async def validate_integrity(
        self,
        project_id: str,
    ) -> Dict[str, Any]:
        """Validate data integrity."""
        return {
            "valid": True,
            "checks_performed": ["in_memory_check"],
            "issues": [],
            "orphaned_chunks": 0,
            "orphaned_entities": 0,
            "recommendations": [],
        }

    async def cleanup_orphaned_data(
        self,
        project_id: str,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        """Clean up orphaned data."""
        return {
            "dry_run": dry_run,
            "chunks_affected": 0,
            "entities_affected": 0,
            "relationships_affected": 0,
            "total_records": 0,
        }

    async def get_storage_stats(self) -> Dict[str, int]:
        """Get in-memory storage statistics."""
        return {
            "total_bytes": 0,  # Not tracked for in-memory
            "table_count": 3,
            "row_count": (
                len(self._chunks) + len(self._entities) + len(self._relationships)
            ),
        }

    # =========================================================================
    # Helper Methods
    # =========================================================================

    @staticmethod
    def _dict_to_chunk(data: Dict[str, Any]) -> DocumentChunk:
        """Convert dict to DocumentChunk."""
        from datetime import datetime, timezone

        # Handle datetime fields
        indexed_at = data.get("indexed_at")
        if isinstance(indexed_at, str):
            indexed_at = datetime.fromisoformat(indexed_at)
        elif indexed_at is None:
            indexed_at = datetime.now(timezone.utc)

        source_modified_at = data.get("source_modified_at")
        if isinstance(source_modified_at, str):
            source_modified_at = datetime.fromisoformat(source_modified_at)
        elif source_modified_at is None:
            source_modified_at = datetime.fromtimestamp(0, tz=timezone.utc)

        return DocumentChunk(
            id=data["id"],
            doc_id=data["doc_id"],
            file_path=data["file_path"],
            project_id=data["project_id"],
            content=data["content"],
            fts_text=data["fts_text"],
            vector=data["vector"],
            content_type=data.get("content_type", "PROSE"),
            language=data.get("language", ""),
            page_number=data.get("page_number", -1),
            line_start=data.get("line_start", -1),
            line_end=data.get("line_end", -1),
            chunk_index=data.get("chunk_index", 0),
            total_chunks=data.get("total_chunks", 1),
            element_type=data.get("element_type", ""),
            element_name=data.get("element_name", ""),
            parent_id=data.get("parent_id", ""),
            child_ids=data.get("child_ids", []),
            symbols=data.get("symbols", []),
            indexed_at=indexed_at,
            source_modified_at=source_modified_at,
            metadata=data.get("metadata", {}),
            ranking_signals=data.get("ranking_signals", {}),
        )

    @staticmethod
    def _dict_to_entity(data: Dict[str, Any]) -> GraphEntity:
        """Convert dict to GraphEntity."""
        return GraphEntity(
            id=data["id"],
            name=data["name"],
            type=data["type"],
            file_path=data["file_path"],
            doc_id=data["doc_id"],
            project_id=data["project_id"],
            vector=data["vector"],
            line_start=data.get("line_start", -1),
            line_end=data.get("line_end", -1),
            pagerank=data.get("pagerank"),
            betweenness=data.get("betweenness"),
            community_id=data.get("community_id"),
            has_ranking_signals=data.get("has_ranking_signals", False),
        )

    @staticmethod
    def _dict_to_relationship(data: Dict[str, Any]) -> GraphRelationship:
        """Convert dict to GraphRelationship."""
        return GraphRelationship(
            id=data["id"],
            source_id=data["source_id"],
            target_id=data["target_id"],
            type=data["type"],
            project_id=data["project_id"],
            vector=data["vector"],
            metadata=data.get("metadata"),
        )


# Aliases for registry compatibility
# The registry expects separate provider classes for each role,
# but InMemoryProvider supports both vector and graph roles
InMemoryVectorProvider = InMemoryProvider
InMemoryGraphProvider = InMemoryProvider


__all__ = [
    "InMemoryProvider",
    # Aliases for registry
    "InMemoryVectorProvider",
    "InMemoryGraphProvider",
]
