"""LanceDB vector storage provider.

This module provides the LanceDBVectorProvider class that implements
VectorStorageProtocol using LanceDB as the storage backend.

The provider delegates lifecycle management to LanceDBConnectionManager
and focuses on vector-specific operations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Sequence, Union

from agentic_inquiry.database.filters import LanceDBFilterAdapter, and_, eq
from agentic_inquiry.database.results import SearchResult
from agentic_inquiry.models.document_chunk import BRANCH_INDEXING_FIELDS, DocumentChunk
from agentic_inquiry.models.graph_entity import GraphEntity
from agentic_inquiry.storage.providers.lancedb.entity_rows import (
    GRAPH_ENTITIES_TABLE,
    dict_to_graph_entity,
)

if TYPE_CHECKING:
    from agentic_inquiry.storage.providers.lancedb.connection import (
        LanceDBConnectionManager,
    )

logger = logging.getLogger(__name__)

# Table and column constants
DOCUMENT_CHUNKS_TABLE = "document_chunks"
VECTOR_COLUMN = "vector"


class LanceDBVectorProvider:
    """LanceDB implementation of VectorStorageProtocol.

    This provider implements vector search and document storage operations
    using LanceDB. It delegates connection management to LanceDBConnectionManager.

    Attributes:
        connection_manager: Shared connection manager
        project_id: Project identifier for data isolation
        SUPPORTED_ROLES: Storage roles this provider supports

    Example:
        >>> manager = LanceDBConnectionManager(config, "my-project")
        >>> await manager.initialize()
        >>> vector_provider = LanceDBVectorProvider(manager)
        >>> await vector_provider.upsert_chunks(chunks, "my-project")
    """

    SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset({"vector"})

    def __init__(
        self,
        connection_manager: "LanceDBConnectionManager",
    ) -> None:
        """Initialize vector provider.

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

    # =========================================================================
    # VectorStorageProtocol Implementation
    # =========================================================================

    async def upsert_chunks(
        self,
        chunks: Sequence[DocumentChunk],
        project_id: str,
    ) -> int:
        """Insert or update document chunks.

        Args:
            chunks: Document chunks to upsert
            project_id: Project ID for isolation

        Returns:
            Number of chunks upserted
        """
        if not chunks:
            return 0

        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        # Convert chunks to dicts for LanceDBManager
        # Use chunk.to_dict() to include all fields expected by the schema
        # Strip branch-indexing fields that may not exist in LanceDB schema yet
        records = []
        for chunk in chunks:
            record = chunk.to_dict()
            # Override project_id with the one from the method argument
            record["project_id"] = project_id
            # Remove branch-indexing fields not yet in LanceDB schema
            for field in BRANCH_INDEXING_FIELDS:
                record.pop(field, None)
            records.append(record)

        await self._db_manager.add_document_chunks(records)
        return len(records)

    async def delete_chunks_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> int:
        """Delete all chunks from a specific file.

        Args:
            file_path: Path to the source file
            project_id: Project ID for isolation

        Returns:
            Number of chunks deleted
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        # Get chunks by file first to get IDs
        # Pass project_id=None to disable auto-filtering since we include it in filters
        results = await self._db_manager.advanced_filter(
            table_name=DOCUMENT_CHUNKS_TABLE,
            filters={"file_path": file_path, "project_id": project_id},
            limit=10000,
            project_id=None,  # Explicit: use filter dict, not auto-add
        )

        if not results:
            return 0

        # Delete by IDs - filter to only valid string IDs
        chunk_ids: List[str] = [
            r["id"] for r in results if r.get("id") and isinstance(r["id"], str)
        ]
        if chunk_ids:
            await self._db_manager.delete_document_chunks(chunk_ids)

        return len(chunk_ids)

    async def delete_chunks_by_ids(
        self,
        chunk_ids: List[str],
        project_id: str,
    ) -> int:
        """Delete chunks by their IDs.

        Args:
            chunk_ids: IDs of chunks to delete
            project_id: Project ID for isolation

        Returns:
            Number of chunks deleted
        """
        if not chunk_ids:
            return 0

        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        await self._db_manager.delete_document_chunks(chunk_ids)
        return len(chunk_ids)

    async def get_chunks_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> List[DocumentChunk]:
        """Get all chunks from a specific file.

        Args:
            file_path: Path to the source file
            project_id: Project ID for isolation

        Returns:
            List of DocumentChunk objects from the file
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        # Use advanced_filter to query by file_path
        # Pass project_id=None to disable auto-filtering since we include it in filters
        results = await self._db_manager.advanced_filter(
            table_name=DOCUMENT_CHUNKS_TABLE,
            filters={"file_path": file_path, "project_id": project_id},
            limit=10000,
            project_id=None,  # Explicit: use filter dict, not auto-add
        )

        chunks = []
        for record in results:
            chunk = self._dict_to_document_chunk(record)
            if chunk:
                chunks.append(chunk)

        return chunks

    async def vector_search(
        self,
        query_vector: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Perform vector similarity search.

        Args:
            query_vector: Query embedding vector
            limit: Maximum number of results
            filters: Optional metadata filters
            project_id: Optional project scope

        Returns:
            List of SearchResult objects sorted by similarity
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        effective_project_id = project_id or self._project_id

        results = await self._db_manager.vector_search(
            table_name=DOCUMENT_CHUNKS_TABLE,
            query_vector=query_vector,
            vector_column_name=VECTOR_COLUMN,
            limit=limit,
            filters=filters,
            project_id=effective_project_id,
        )

        # Convert dict results to SearchResult objects
        return self._dicts_to_search_results(results, source="vector")

    async def fts_search(
        self,
        query: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Perform full-text search.

        Args:
            query: Search query text
            limit: Maximum number of results
            filters: Optional metadata filters
            project_id: Optional project scope

        Returns:
            List of SearchResult objects sorted by relevance
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        effective_project_id = project_id or self._project_id

        results = await self._db_manager.fts_search(
            table_name=DOCUMENT_CHUNKS_TABLE,
            query=query,
            limit=limit,
            filters=filters,
            project_id=effective_project_id,
        )

        return self._dicts_to_search_results(results, source="fts")

    async def hybrid_search(
        self,
        query_vector: List[float],
        query_text: str,
        limit: int = 10,
        vector_weight: float = 0.7,
        project_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Perform hybrid vector + FTS search.

        Args:
            query_vector: Query embedding vector
            query_text: Query text for FTS
            limit: Maximum number of results
            vector_weight: Weight for vector results (0.0-1.0)
            project_id: Optional project scope

        Returns:
            List of SearchResult objects with combined ranking
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        effective_project_id = project_id or self._project_id

        results = await self._db_manager.hybrid_search(
            table_name=DOCUMENT_CHUNKS_TABLE,
            query=query_text,
            query_vector=query_vector,
            vector_column_name=VECTOR_COLUMN,
            limit=limit,
            filters=None,
            project_id=effective_project_id,
        )

        return self._dicts_to_search_results(results, source="hybrid")

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
            limit: Maximum number of results
            offset: Number of results to skip
            project_id: Optional project scope

        Returns:
            List of matching DocumentChunk objects
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        effective_project_id = project_id or self._project_id

        # Add project_id to filters if provided
        query_filters = dict(filters)
        if effective_project_id:
            query_filters["project_id"] = effective_project_id

        results = await self._db_manager.advanced_filter(
            table_name=DOCUMENT_CHUNKS_TABLE,
            filters=query_filters,
            limit=limit + offset,  # Offset handled manually
        )

        chunks = []
        for record in results[offset:]:
            chunk = self._dict_to_document_chunk(record)
            if chunk:
                chunks.append(chunk)

        return chunks

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
        """Search entities by LanceDB vector similarity.

        Reads from the ``graph_entities`` table — owned structurally by
        :class:`LanceDBGraphProvider` but queried here because similarity
        search is a vector-space op that shares its code path with chunk
        search. Returns entities sorted by ascending distance with
        ``_distance`` annotated on each.

        LanceDB has no server-side embedding; a raw ``str`` query would
        otherwise be interpreted by ``table.search(str)`` as an FTS
        query, silently returning weird results. Reject it explicitly so
        the protocol's "SHOULD raise for str input" clause is honoured.
        """
        import asyncio

        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        if isinstance(query_vector, str):
            raise TypeError(
                "LanceDBVectorProvider does not support server-side embedding; "
                "entity_vector_search requires a list of floats, got str."
            )

        # ``get_table`` returns None for the expected missing-table case
        # (nothing has been indexed yet) — handle that explicitly and let
        # every other failure propagate. The previous blanket
        # ``except Exception: return []`` made genuine query / schema
        # failures indistinguishable from "no matches", which masked bugs
        # (including the ``get_table`` method-not-found bug on main) and
        # complicated debugging of the canonical entity-search path.
        table = await self._db_manager.get_table(GRAPH_ENTITIES_TABLE)
        if table is None:
            logger.debug(
                "Entity vector search skipped: %r not created yet",
                GRAPH_ENTITIES_TABLE,
            )
            return []

        search_builder = table.search(query_vector)

        # Route through the canonical filter AST so string values are
        # single-quote-escaped by ``translate_filter`` (``'`` → ``''``).
        # The previous f-string path broke on ``project_id`` values
        # containing apostrophes and was expression-injectable if any
        # caller passed user-controlled values through.
        scope_filter = eq("project_id", project_id)
        if entity_type:
            scope_filter = and_(scope_filter, eq("type", entity_type))
        where_expr = LanceDBFilterAdapter().translate(scope_filter)
        if where_expr:
            search_builder = search_builder.where(where_expr)

        loop = asyncio.get_running_loop()
        raw_results = await loop.run_in_executor(
            None, search_builder.limit(limit).to_list
        )

        entities: List[GraphEntity] = []
        for result in raw_results:
            entity = dict_to_graph_entity(result)
            if entity is not None:
                entity._distance = result.get("_distance", 1.0)
                entities.append(entity)

        logger.debug(
            "Entity vector search found %d entities (limit=%d, type=%s)",
            len(entities),
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
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        effective_project_id = project_id or self._project_id

        return await self._db_manager.count_records(
            table_name=DOCUMENT_CHUNKS_TABLE,
            filters=filters,
            project_id=effective_project_id,
        )

    async def query_across_projects(
        self,
        table_name: str,
        project_ids: Sequence[str],
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query data across multiple projects.

        Args:
            table_name: Logical table to query
            project_ids: List of project IDs to include
            filters: Optional filter conditions
            limit: Maximum number of results

        Returns:
            List of matching records as dictionaries
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        return await self._db_manager.query_across_projects(
            table_name=table_name,
            project_ids=list(project_ids),
            filters=filters or {},
            limit=limit,
        )

    async def list_tables(self) -> List[str]:
        """List all tables in the storage.

        Returns:
            List of table names
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        return await self._db_manager.list_tables()

    async def table_exists(self, table_name: str) -> bool:
        """Check if a table exists.

        Args:
            table_name: Name of the table

        Returns:
            True if table exists
        """
        tables = await self.list_tables()
        return table_name in tables

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _dicts_to_search_results(
        self,
        records: List[Dict[str, Any]],
        source: str = "vector",
    ) -> List[SearchResult]:
        """Convert dict records to SearchResult objects.

        Args:
            records: List of dict records from database
            source: Source type (vector, fts, hybrid)

        Returns:
            List of SearchResult objects
        """
        results = []
        for i, record in enumerate(records):
            # Extract score from _distance or _score field
            distance = record.get("_distance")
            score = record.get("_score", record.get("score", 0.0))

            # Calculate score from distance if needed
            if distance is not None and score == 0.0:
                # Convert distance to similarity score (assumes cosine distance)
                # Clamp to [0.0, 1.0] to handle floating point precision issues
                score = max(0.0, min(1.0, 1.0 - distance))

            # Ensure score is clamped to valid range
            final_score = max(0.0, min(1.0, score if score is not None else 0.0))

            result = SearchResult(
                id=record.get("id", f"unknown_{i}"),
                data=record,
                score=final_score,
                source=source,
                distance=distance,
            )
            results.append(result)

        return results

    def _dict_to_document_chunk(
        self, record: Dict[str, Any]
    ) -> Optional[DocumentChunk]:
        """Convert a dict record to DocumentChunk.

        Args:
            record: Dict from database

        Returns:
            DocumentChunk or None if conversion fails
        """
        try:
            return DocumentChunk(
                id=record.get("id", ""),
                doc_id=record.get("doc_id", ""),
                project_id=record.get("project_id", ""),
                content=record.get("content", ""),
                fts_text=record.get("fts_text", ""),
                file_path=record.get("file_path", ""),
                content_type=record.get("content_type", "PROSE"),
                vector=record.get("vector", []),
                metadata=record.get("metadata", {}),
                line_start=record.get("line_start", -1),
                line_end=record.get("line_end", -1),
                chunk_index=record.get("chunk_index", 0),
                language=record.get("language", ""),
                symbols=record.get("symbols", []),
            )
        except Exception as e:
            logger.warning("Failed to convert record to DocumentChunk: %s", e)
            return None
