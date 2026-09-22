"""Indexing storage protocol for IndexingPipeline abstraction.

This module defines the protocol that all indexing storage providers must implement.
It provides the methods needed by IndexingPipeline, GraphBuilder, and related
indexing components.

Protocols defined:
    - IndexingStorageProtocol: Methods for document indexing operations

Design principles:
    - Minimal surface area: Only methods needed for indexing
    - Capability-based: Check capabilities at runtime with isinstance()
    - Dict-based: Uses dict for batch operations (not domain objects)
    - Async-only: All I/O operations are async
"""

from __future__ import annotations

from typing import (
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    runtime_checkable,
)

from agent_vault.constants import CURRENT_PROJECT_ID


@runtime_checkable
class IndexingStorageProtocol(Protocol):
    """Protocol for indexing storage operations.

    This protocol defines the methods needed by IndexingPipeline and related
    components for document indexing, graph construction, and cleanup.

    Methods use dict-based records for batch efficiency rather than
    domain objects like DocumentChunk or GraphEntity.

    Implementations:
        - LanceDBAdapter: Full implementation wrapping LanceDBManager
        - InMemoryProvider: Testing implementation

    Example:
        >>> storage: IndexingStorageProtocol = LanceDBAdapter(manager)
        >>> await storage.add_document_chunks(chunk_dicts, project_id="proj")
        >>> await storage.add_graph_entities(entity_dicts)
        >>> results = await storage.advanced_filter(
        ...     table_name="graph_entities",
        ...     filters={"type": "function"},
        ...     limit=100
        ... )
    """

    # =========================================================================
    # Document Chunk Operations
    # =========================================================================

    async def add_document_chunks(
        self,
        chunks: List[Any],
        project_id: str = CURRENT_PROJECT_ID,
        ensure_commit: bool = True,
    ) -> None:
        """Add document chunks to the database.

        Batch add chunks for efficient bulk inserts. Accepts either dictionaries
        or DocumentChunk objects (which have to_dict() method).

        Args:
            chunks: List of chunk dictionaries or DocumentChunk objects
            project_id: Project identifier for data isolation (default: CURRENT_PROJECT_ID)
            ensure_commit: Accepted for interface compatibility; backends commit
                before the call returns
        """
        ...

    async def delete_document_chunks(
        self,
        chunk_ids: List[str],
    ) -> None:
        """Delete document chunks by ID.

        Args:
            chunk_ids: List of chunk IDs to delete
        """
        ...

    # =========================================================================
    # Graph Entity Operations
    # =========================================================================

    async def add_graph_entities(
        self,
        entities: List[Any],
    ) -> None:
        """Add graph entities to the database.

        Batch add entities for efficient bulk inserts. Accepts either dictionaries
        or GraphEntity objects (which have to_dict() method).

        Args:
            entities: List of entity dictionaries or GraphEntity objects
        """
        ...

    async def delete_graph_entities(
        self,
        entity_ids: List[str],
    ) -> None:
        """Delete graph entities by ID.

        Args:
            entity_ids: List of entity IDs to delete
        """
        ...

    # =========================================================================
    # Graph Relationship Operations
    # =========================================================================

    async def add_graph_relationships(
        self,
        relationships: List[Any],
    ) -> None:
        """Add graph relationships to the database.

        Batch add relationships for efficient bulk inserts. Accepts either dictionaries
        or GraphRelationship objects (which have to_dict() method).

        Args:
            relationships: List of relationship dictionaries or GraphRelationship objects
        """
        ...

    async def delete_graph_relationships(
        self,
        relationship_ids: List[str],
    ) -> None:
        """Delete graph relationships by ID.

        Args:
            relationship_ids: List of relationship IDs to delete
        """
        ...

    # =========================================================================
    # Query Operations
    # =========================================================================

    async def advanced_filter(
        self,
        table_name: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        project_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query records with filtering.

        Args:
            table_name: Logical table name (document_chunks, graph_entities, etc.)
            filters: Filter conditions as dict
            limit: Maximum records to return
            project_id: Optional project scope

        Returns:
            List of matching records as dictionaries
        """
        ...

    async def query_entities(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        project_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query graph entities with filters.

        Args:
            filters: Optional filter conditions as key-value pairs
            limit: Maximum number of results
            project_id: Optional project scope

        Returns:
            List of entity dictionaries matching the query
        """
        ...

    # =========================================================================
    # Maintenance Operations
    # =========================================================================

    async def run_maintenance(self) -> Dict[str, Any]:
        """Run database maintenance operations.

        Performs compaction, optimization, and cleanup tasks.
        Should be called periodically or after large batch operations.

        Returns:
            Dict with maintenance results including summary stats
        """
        ...


def has_indexing_support(obj: Any) -> bool:
    """Check if an object implements IndexingStorageProtocol.

    Args:
        obj: Object to check

    Returns:
        True if obj implements IndexingStorageProtocol
    """
    return isinstance(obj, IndexingStorageProtocol)
