"""Vector storage protocol for provider abstraction.

This module defines the protocols that all vector storage providers must implement.
It provides comprehensive coverage of operations needed for the indexing pipeline,
search services, and maintenance operations.

Protocols defined:
    - VectorStorageProtocol: Core CRUD and search operations (14 methods)
    - MaintenanceProtocol: Health checks, compaction, and integrity validation
    - TransactionProtocol: Atomic operations with rollback support

Design principles:
    - Minimal surface area: Only methods that vary across backends
    - Capability-based: Check capabilities at runtime with isinstance()
    - Canonical types: All methods use DocumentChunk and SearchResult
    - Async-only: All I/O operations are async
"""

from __future__ import annotations

from typing import (
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    Sequence,
    Union,
    runtime_checkable,
)

from agentic_inquiry.database.results import SearchResult
from agentic_inquiry.models.document_chunk import DocumentChunk
from agentic_inquiry.models.graph_entity import GraphEntity


# =============================================================================
# Transaction Context Protocol
# =============================================================================


@runtime_checkable
class TransactionContext(Protocol):
    """Protocol for transactional operations context manager.

    Provides atomic operation semantics with automatic rollback on failure.
    Use with `async with` statement for proper cleanup.

    Example:
        >>> async with provider.begin_transaction() as txn:
        ...     txn.add_operation("upsert_chunks", "document_chunks", chunks)
        ...     txn.add_operation("upsert_entities", "graph_entities", entities)
        ...     await txn.flush()
        ... # Auto-commits on success, rolls back on exception

    Implementations must provide all methods defined in this protocol.
    """

    async def __aenter__(self) -> TransactionContext:
        """Enter transaction context.

        Returns:
            Self for use in async with statement.
        """
        ...

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> bool:
        """Exit transaction context.

        Commits on success, rolls back on exception.

        Args:
            exc_type: Exception type if an error occurred.
            exc_val: Exception value if an error occurred.
            exc_tb: Exception traceback if an error occurred.

        Returns:
            False to propagate exceptions, True to suppress.
        """
        ...

    def add_operation(
        self,
        operation_type: str,
        table_name: str,
        data: Any,
        rollback_operation: Optional[Any] = None,
    ) -> None:
        """Add operation to transaction.

        Operations are queued and executed atomically on flush/commit.

        Args:
            operation_type: Type of operation. Supported types:
                - "upsert_chunks": Insert/update document chunks
                - "upsert_entities": Insert/update graph entities
                - "upsert_relationships": Insert/update relationships
                - "delete": Delete records by filter
            table_name: Target table name (logical name).
            data: Operation data (format depends on operation_type).
            rollback_operation: Optional callable for rollback.
                If provided, will be called with original data on rollback.

        Example:
            >>> txn.add_operation(
            ...     "upsert_chunks",
            ...     "document_chunks",
            ...     chunks,
            ...     rollback_operation=delete_chunks_by_ids
            ... )
        """
        ...

    async def flush(self, ensure_commit: bool = True) -> None:
        """Flush pending operations.

        Executes all queued operations. Backends commit each write before
        the write call returns, so this does no extra visibility work.

        Args:
            ensure_commit: Accepted for interface compatibility.

        Raises:
            RuntimeError: If flush fails (transaction will be rolled back).
        """
        ...


# =============================================================================
# Vector Storage Protocol (Required)
# =============================================================================


@runtime_checkable
class VectorStorageProtocol(Protocol):
    """Vector storage operations - comprehensive coverage of LanceDBManager usage.

    This protocol defines the contract for vector storage providers. Implementations
    must support all methods for storage, search, and table management operations.

    All operations are async and must be called within an async context.

    Lifecycle:
        >>> provider = MyVectorProvider.from_config(config)
        >>> await provider.initialize()
        >>> # ... use provider ...
        >>> await provider.close()

    Project Isolation:
        Most operations accept a project_id parameter for multi-tenant data
        isolation. Implementations should scope data access to the specified
        project.

    Example:
        >>> class LanceDBProvider:
        ...     async def initialize(self) -> None:
        ...         self._db = await lancedb.connect_async(self.db_path)
        ...
        ...     async def vector_search(
        ...         self, query_vector: List[float], limit: int = 10, ...
        ...     ) -> List[SearchResult]:
        ...         table = await self._db.open_table("document_chunks")
        ...         results = await table.search(query_vector).limit(limit).to_list()
        ...         return [dict_to_search_result(r, "vector") for r in results]
    """

    # =========================================================================
    # Lifecycle Methods
    # =========================================================================

    async def initialize(self) -> None:
        """Initialize the storage backend connection.

        Must be called before any other operations. Safe to call multiple times
        (idempotent). Creates required tables if they don't exist.

        Raises:
            StorageError: If connection fails.
            RuntimeError: If initialization fails.

        Example:
            >>> provider = MyVectorProvider.from_config(config)
            >>> await provider.initialize()  # Creates tables, connects
            >>> await provider.initialize()  # No-op, already initialized
        """
        ...

    async def close(self) -> None:
        """Close the storage backend connection.

        Releases all resources including connections, file handles, and
        cached data. Safe to call multiple times (idempotent).

        Example:
            >>> await provider.close()  # Cleanup
            >>> await provider.close()  # No-op, already closed
        """
        ...

    # =========================================================================
    # Core CRUD Operations
    # =========================================================================

    async def upsert_chunks(
        self, chunks: Sequence[DocumentChunk], project_id: str
    ) -> int:
        """Insert or update document chunks.

        If a chunk with the same ID exists, updates it. Otherwise, inserts
        a new record. Vectors are stored for similarity search.

        Args:
            chunks: Sequence of DocumentChunk objects to upsert.
                Each chunk must have a valid id, project_id matching
                the provided project_id, and a non-empty vector.
            project_id: Project scope for isolation. Must match
                chunk.project_id for all provided chunks.

        Returns:
            Number of chunks upserted (inserts + updates).

        Raises:
            ValueError: If chunks have mismatched project_id.
            StorageError: If upsert fails.

        Example:
            >>> chunks = [DocumentChunk(id="c1", ...), DocumentChunk(id="c2", ...)]
            >>> count = await provider.upsert_chunks(chunks, "my_project")
            >>> print(f"Upserted {count} chunks")
        """
        ...

    async def delete_chunks_by_file(self, file_path: str, project_id: str) -> int:
        """Delete all chunks from a specific file.

        Removes all document chunks that were indexed from the specified
        source file. Used for re-indexing and cleanup operations.

        Args:
            file_path: Path to the source file. Should be an absolute path
                or consistent relative path matching indexed chunks.
            project_id: Project scope for isolation.

        Returns:
            Number of chunks deleted.

        Example:
            >>> deleted = await provider.delete_chunks_by_file(
            ...     "/src/main.py", "my_project"
            ... )
            >>> print(f"Deleted {deleted} chunks from main.py")
        """
        ...

    async def delete_chunks_by_ids(self, chunk_ids: List[str], project_id: str) -> int:
        """Delete chunks by their IDs.

        Removes specific document chunks by their unique identifiers.

        Args:
            chunk_ids: List of chunk IDs to delete.
            project_id: Project scope for isolation.

        Returns:
            Number of chunks deleted (may be less than len(chunk_ids)
            if some IDs don't exist).

        Example:
            >>> deleted = await provider.delete_chunks_by_ids(
            ...     ["chunk_001", "chunk_002"], "my_project"
            ... )
        """
        ...

    async def get_chunks_by_file(
        self, file_path: str, project_id: str
    ) -> List[DocumentChunk]:
        """Get all chunks from a specific file.

        Retrieves all document chunks that were indexed from the specified
        source file. Useful for inspection and re-indexing decisions.

        Args:
            file_path: Path to the source file.
            project_id: Project scope for isolation.

        Returns:
            List of DocumentChunk objects from the file.
            Empty list if no chunks found.

        Example:
            >>> chunks = await provider.get_chunks_by_file(
            ...     "/src/main.py", "my_project"
            ... )
            >>> print(f"Found {len(chunks)} chunks")
        """
        ...

    # =========================================================================
    # Search Operations
    # =========================================================================

    async def vector_search(
        self,
        query_vector: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Perform vector similarity search.

        Finds documents most similar to the query vector using cosine
        similarity or L2 distance (implementation-dependent).

        Args:
            query_vector: Query embedding vector. Must have the same
                dimensions as stored vectors (typically 384 or 768).
            limit: Maximum number of results to return.
            filters: Optional metadata filters. Keys are field names,
                values are exact match values or filter expressions.
                Example: {"content_type": "CODE", "language": "python"}
            project_id: Optional project scope. If None, searches all
                projects (use with caution in multi-tenant environments).

        Returns:
            List of SearchResult objects ranked by similarity (highest
            similarity first). Each result has:
            - id: Chunk ID
            - data: Original chunk data as dict
            - score: Normalized similarity score (0.0-1.0)
            - source: "vector"
            - distance: Optional raw distance value

        Example:
            >>> query_vec = await embedder.embed("authentication error")
            >>> results = await provider.vector_search(
            ...     query_vec, limit=5, filters={"content_type": "CODE"}
            ... )
            >>> for r in results:
            ...     print(f"{r.score:.3f}: {r.data['file_path']}")
        """
        ...

    async def fts_search(
        self,
        query: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Perform full-text search.

        Searches text content using BM25 or similar text ranking algorithm.
        Supports phrase queries and boolean operators (implementation-dependent).

        Args:
            query: Search query string. Special characters may need escaping
                depending on the backend.
            limit: Maximum number of results to return.
            filters: Optional metadata filters (same as vector_search).
            project_id: Optional project scope.

        Returns:
            List of SearchResult objects ranked by relevance (highest
            relevance first). Each result has:
            - id: Chunk ID
            - data: Original chunk data as dict
            - score: Normalized relevance score (0.0-1.0)
            - source: "fts"

        Example:
            >>> results = await provider.fts_search(
            ...     "authentication error handling",
            ...     limit=10,
            ...     filters={"language": "python"}
            ... )
        """
        ...

    async def hybrid_search(
        self,
        query_vector: List[float],
        query_text: str,
        limit: int = 10,
        vector_weight: float = 0.7,
        project_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Perform hybrid vector + FTS search.

        Combines vector similarity and full-text search results using
        Reciprocal Rank Fusion (RRF) or weighted linear combination.

        Args:
            query_vector: Query embedding vector.
            query_text: Query text for FTS.
            limit: Maximum number of results to return.
            vector_weight: Weight for vector results (0.0-1.0).
                FTS weight = 1 - vector_weight.
            project_id: Optional project scope.

        Returns:
            List of SearchResult objects with combined ranking.
            Each result has:
            - id: Chunk ID
            - data: Original chunk data as dict
            - score: Combined normalized score (0.0-1.0)
            - source: "hybrid"

        Example:
            >>> query_vec = await embedder.embed("how to authenticate users")
            >>> results = await provider.hybrid_search(
            ...     query_vec,
            ...     "authenticate users login",
            ...     limit=10,
            ...     vector_weight=0.6
            ... )
        """
        ...

    # =========================================================================
    # Query Operations (Used by IndexingPipeline cleanup)
    # =========================================================================

    async def query(
        self,
        filters: Dict[str, Any],
        limit: int = 100,
        offset: int = 0,
        project_id: Optional[str] = None,
    ) -> List[DocumentChunk]:
        """Query chunks with filters.

        Retrieves chunks matching the specified filter criteria. Used for
        cleanup operations and batch processing.

        Args:
            filters: Filter conditions as key-value pairs.
                Keys are field names, values are exact match values.
                Example: {"file_path": "/src/main.py"}
            limit: Maximum number of results to return.
            offset: Number of results to skip (for pagination).
            project_id: Optional project scope.

        Returns:
            List of matching DocumentChunk objects.

        Example:
            >>> chunks = await provider.query(
            ...     {"content_type": "CODE", "language": "python"},
            ...     limit=100,
            ...     project_id="my_project"
            ... )
        """
        ...

    async def count(
        self,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> int:
        """Count chunks matching filters.

        Returns the number of chunks matching the filter criteria without
        retrieving the actual data.

        Args:
            filters: Optional filter conditions. If None, counts all chunks.
            project_id: Optional project scope. If None with no filters,
                counts all chunks across all projects.

        Returns:
            Number of matching chunks.

        Example:
            >>> total = await provider.count(project_id="my_project")
            >>> code_count = await provider.count(
            ...     {"content_type": "CODE"}, project_id="my_project"
            ... )
            >>> print(f"{code_count}/{total} chunks are code")
        """
        ...

    # =========================================================================
    # Entity Vector Search
    # =========================================================================
    #
    # Entity embeddings are a vector-space operation even though the entity
    # *records* (id, name, file_path, etc.) are owned by the graph backend.
    # The vector provider performs similarity search against the embedding
    # column and returns the hydrated :class:`GraphEntity` rows so callers
    # can do one query instead of a vector-search-plus-row-lookup.
    #
    # Previously this method lived on ``GraphStorageProtocol`` — see the
    # ``feat/vector-owns-entity-search`` branch history for the rationale.

    async def entity_vector_search(
        self,
        query_vector: Union[str, List[float]],
        project_id: str,
        limit: int = 50,
        entity_type: Optional[str] = None,
    ) -> List[GraphEntity]:
        """Search entities by vector similarity.

        Performs similarity search on entity embeddings to find entities most
        similar to the query vector. This enables semantic search over the
        code graph beyond simple name matching.

        Args:
            query_vector: Query embedding vector (list of floats matching
                the stored embedding dim, typically 384), or a raw ``str``
                query when the backend supports server-side embedding
                (AlloyDB's ``embedding()`` function, RDS via Bedrock).
                Backends without server-side embedding MUST accept the
                list-of-floats form and SHOULD raise for ``str`` input.
            project_id: Project scope for data isolation.
            limit: Maximum number of results to return. Default is 50.
            entity_type: Optional filter by entity type (e.g. ``"function"``,
                ``"class"``). If None, searches all entity types.

        Returns:
            List of :class:`GraphEntity` objects ranked by similarity (most
            similar first). Each entity is annotated with a ``_distance``
            attribute holding the raw distance value from the index.
        """
        ...

    # =========================================================================
    # Multi-Project Query Operations
    # =========================================================================

    async def query_across_projects(
        self,
        table_name: str,
        project_ids: Sequence[str],
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query data across multiple projects.

        Used by GraphSearchService for multi-project graph traversal and search
        operations. Allows querying document_chunks, graph_entities, or
        graph_relationships across project boundaries.

        Args:
            table_name: Logical table to query ("document_chunks",
                "graph_entities", "graph_relationships").
            project_ids: List of project IDs to include in the query.
            filters: Optional filter conditions applied within each project.
            limit: Maximum number of results to return. Default is 100.

        Returns:
            List of matching records as dictionaries.

        Example:
            >>> entities = await provider.query_across_projects(
            ...     "graph_entities",
            ...     ["project_a", "project_b"],
            ...     filters={"type": "function"},
            ...     limit=50
            ... )
            >>> print(f"Found {len(entities)} functions across projects")
        """
        ...

    # =========================================================================
    # Table Management
    # =========================================================================

    async def list_tables(self) -> List[str]:
        """List all tables in the storage.

        Returns logical table names (e.g., "document_chunks", "graph_entities").

        Returns:
            List of table names.

        Example:
            >>> tables = await provider.list_tables()
            >>> print(f"Tables: {tables}")
            Tables: ['document_chunks', 'graph_entities', 'graph_relationships']
        """
        ...

    async def table_exists(self, table_name: str) -> bool:
        """Check if a table exists.

        Args:
            table_name: Name of the table to check (logical name).

        Returns:
            True if table exists, False otherwise.

        Example:
            >>> if await provider.table_exists("document_chunks"):
            ...     print("Chunks table ready")
        """
        ...


# =============================================================================
# Maintenance Protocol (Required for IndexingPipeline compatibility)
# =============================================================================


@runtime_checkable
class MaintenanceProtocol(Protocol):
    """Maintenance operations - REQUIRED for IndexingPipeline compatibility.

    Provides health checks, compaction, integrity validation, and cleanup
    operations essential for production deployments.

    Example:
        >>> health = await provider.health_check()
        >>> if health["status"] == "healthy":
        ...     result = await provider.run_maintenance("my_project")
        ...     print(f"Reduced {result['fragments_reduced']} fragments")
    """

    async def health_check(self) -> Dict[str, Any]:
        """Check storage health.

        Performs connectivity and integrity checks on the storage backend.

        Returns:
            Dict with health status information:
            - status: "healthy", "degraded", or "unhealthy"
            - latency_ms: Connection latency in milliseconds
            - table_count: Number of tables
            - error: Error message if unhealthy (optional)

        Example:
            >>> health = await provider.health_check()
            >>> print(f"Status: {health['status']}, latency: {health['latency_ms']}ms")
        """
        ...

    async def run_maintenance(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Run storage maintenance operations.

        Performs optimization tasks like fragment consolidation, index
        rebuilding, and cache cleanup.

        Args:
            project_id: Optional project scope. If None, runs maintenance
                on all projects.

        Returns:
            Dict with keys:
            - summary: Human-readable summary
            - fragments_reduced: Number of fragments consolidated
            - bytes_reclaimed: Storage space reclaimed in bytes
            - duration_ms: Operation duration in milliseconds
            - tables_processed: List of tables that were processed

        Example:
            >>> result = await provider.run_maintenance("my_project")
            >>> print(result["summary"])
        """
        ...

    async def compact(self, project_id: Optional[str] = None) -> None:
        """Compact storage to reclaim space.

        Consolidates fragmented data and reclaims deleted space. May be
        expensive for large datasets.

        Args:
            project_id: Optional project scope. If None, compacts all data.

        Example:
            >>> await provider.compact("my_project")
        """
        ...

    async def validate_integrity(self, project_id: str) -> Dict[str, Any]:
        """Validate data integrity.

        Checks for orphaned records, broken references, and data corruption.

        Args:
            project_id: Project scope for validation.

        Returns:
            Dict with validation results:
            - valid: True if all checks pass
            - checks_performed: List of checks run
            - issues: List of issues found (empty if valid)
            - orphaned_chunks: Number of chunks without file references
            - orphaned_entities: Number of entities without relationships
            - recommendations: List of recommended actions

        Example:
            >>> result = await provider.validate_integrity("my_project")
            >>> if not result["valid"]:
            ...     for issue in result["issues"]:
            ...         print(f"Issue: {issue}")
        """
        ...

    async def cleanup_orphaned_data(
        self, project_id: str, dry_run: bool = True
    ) -> Dict[str, Any]:
        """Clean up orphaned data.

        Removes chunks, entities, and relationships that are no longer
        referenced or have broken parent references.

        Args:
            project_id: Project scope for cleanup.
            dry_run: If True, only reports what would be cleaned without
                actually deleting. Set to False to perform cleanup.

        Returns:
            Dict with cleanup results:
            - dry_run: Whether this was a dry run
            - chunks_affected: Number of orphaned chunks found/deleted
            - entities_affected: Number of orphaned entities found/deleted
            - relationships_affected: Number of orphaned relationships found/deleted
            - total_records: Total records affected

        Example:
            >>> # First, see what would be cleaned
            >>> result = await provider.cleanup_orphaned_data("my_project", dry_run=True)
            >>> print(f"Would delete {result['total_records']} records")
            >>> # Then actually clean up
            >>> result = await provider.cleanup_orphaned_data("my_project", dry_run=False)
        """
        ...


# =============================================================================
# Transaction Protocol (Required for IndexingPipeline compatibility)
# =============================================================================


@runtime_checkable
class TransactionProtocol(Protocol):
    """Transaction support - REQUIRED for IndexingPipeline compatibility.

    Provides atomic operations with rollback support for multi-step
    indexing operations.

    Usage with context manager (recommended):
        >>> async with provider.begin_transaction() as txn:
        ...     txn.add_operation("upsert_chunks", "document_chunks", chunks)
        ...     txn.add_operation("upsert_entities", "graph_entities", entities)
        ...     await txn.flush()
        ... # Auto-commits on success, rolls back on exception

    Manual transaction control:
        >>> txn = await provider.begin_transaction()
        >>> try:
        ...     txn.add_operation("upsert_chunks", "document_chunks", chunks)
        ...     await txn.flush()
        ...     await provider.commit()
        ... except Exception:
        ...     await provider.rollback()
        ...     raise
    """

    async def begin_transaction(self) -> TransactionContext:
        """Begin a new transaction.

        Creates a new transaction context for atomic operations.
        Must be used with `async with` or explicit commit/rollback.

        Returns:
            TransactionContext for the transaction.

        Example:
            >>> async with await provider.begin_transaction() as txn:
            ...     txn.add_operation("upsert_chunks", "document_chunks", chunks)
        """
        ...

    async def commit(self) -> None:
        """Commit the current transaction.

        Makes all operations in the current transaction permanent.
        Should only be called after begin_transaction() and before
        any explicit rollback.

        Raises:
            RuntimeError: If no transaction is active.
            StorageError: If commit fails (transaction is rolled back).

        Example:
            >>> await provider.commit()
        """
        ...

    async def rollback(self) -> None:
        """Rollback the current transaction.

        Undoes all operations in the current transaction. Safe to call
        multiple times or when no transaction is active.

        Example:
            >>> await provider.rollback()
        """
        ...


# =============================================================================
# Composite Protocol (Convenience)
# =============================================================================


@runtime_checkable
class FullVectorStorageProtocol(
    VectorStorageProtocol, MaintenanceProtocol, TransactionProtocol, Protocol
):
    """Combined protocol for providers implementing all capabilities.

    Use this when you need a provider with full functionality including
    storage, maintenance, and transaction support.

    Example:
        >>> def process_with_full_provider(provider: FullVectorStorageProtocol):
        ...     # Can use all methods from all protocols
        ...     await provider.initialize()
        ...     async with await provider.begin_transaction() as txn:
        ...         txn.add_operation("upsert_chunks", "document_chunks", chunks)
        ...     await provider.run_maintenance()
    """

    pass


# =============================================================================
# Capability Detection Helpers
# =============================================================================


def has_maintenance_support(provider: VectorStorageProtocol) -> bool:
    """Check if provider supports maintenance operations.

    Args:
        provider: Provider instance to check.

    Returns:
        True if provider implements MaintenanceProtocol.

    Example:
        >>> if has_maintenance_support(provider):
        ...     await provider.run_maintenance("my_project")
    """
    return isinstance(provider, MaintenanceProtocol)


def has_transaction_support(provider: VectorStorageProtocol) -> bool:
    """Check if provider supports transactions.

    Args:
        provider: Provider instance to check.

    Returns:
        True if provider implements TransactionProtocol.

    Example:
        >>> if has_transaction_support(provider):
        ...     async with await provider.begin_transaction() as txn:
        ...         txn.add_operation(...)
    """
    return isinstance(provider, TransactionProtocol)


def is_full_provider(provider: VectorStorageProtocol) -> bool:
    """Check if provider implements all capabilities.

    Args:
        provider: Provider instance to check.

    Returns:
        True if provider implements FullVectorStorageProtocol.

    Example:
        >>> if is_full_provider(provider):
        ...     # Safe to use all features
        ...     pass
    """
    return isinstance(provider, FullVectorStorageProtocol)


def has_vector_search(provider: VectorStorageProtocol) -> bool:
    """Check if provider supports vector search.

    Args:
        provider: Provider instance to check.

    Returns:
        True if provider supports vector search.
    """
    # In the current protocol definition, vector_search is required
    return True


def has_fts(provider: VectorStorageProtocol) -> bool:
    """Check if provider supports full-text search.

    Args:
        provider: Provider instance to check.

    Returns:
        True if provider supports FTS.
    """
    # In the current protocol definition, fts_search is required
    return True


def has_hybrid_search(provider: VectorStorageProtocol) -> bool:
    """Check if provider supports hybrid search.

    Args:
        provider: Provider instance to check.

    Returns:
        True if provider supports hybrid search.
    """
    # In the current protocol definition, hybrid_search is required
    return True


def has_graph_ranking(provider: VectorStorageProtocol) -> bool:
    """Check if provider supports graph ranking.

    Args:
        provider: Provider instance to check.

    Returns:
        True if provider supports graph ranking.
    """
    # Currently not part of the required VectorStorageProtocol, but checked by facade
    return hasattr(provider, "apply_graph_boost")


__all__ = [
    # Core protocols
    "VectorStorageProtocol",
    "MaintenanceProtocol",
    "TransactionProtocol",
    "FullVectorStorageProtocol",
    # Transaction context
    "TransactionContext",
    # Capability detection
    "has_maintenance_support",
    "has_transaction_support",
    "is_full_provider",
    "has_vector_search",
    "has_fts",
    "has_hybrid_search",
    "has_graph_ranking",
]
