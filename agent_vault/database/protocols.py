"""Protocol definitions for database abstraction layer.

This module defines the capability-based protocols that adapters implement.
Protocols use structural subtyping (duck typing) with runtime checking.

Design principles:
- Minimal surface area: Only methods that vary across backends
- Capability-based: Check capabilities at runtime with isinstance()
- Canonical types: All methods use Filter, QuerySpec, and SearchResult
- Async-only: All I/O operations are async

See: docs/design/database-abstraction-revised.md
"""
from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    Sequence,
    runtime_checkable,
)

from agent_vault.database.filters import Filter
from agent_vault.database.query_spec import QuerySpec
from agent_vault.database.results import SearchResult

if TYPE_CHECKING:
    from agent_vault.models.document_chunk import DocumentChunk
    from agent_vault.models.graph_entity import GraphEntity
    from agent_vault.models.graph_relationship import GraphRelationship


# =============================================================================
# Core Storage Protocol (Required)
# =============================================================================


@runtime_checkable
class VectorStorageProtocol(Protocol):
    """Core storage operations that every adapter must support.

    This is the minimal interface required for any vector database adapter.
    All methods operate on logical table names and canonical types.

    Lifecycle:
        adapter = await SomeAdapter.from_config(config)
        await adapter.initialize()  # Ensure tables exist
        # ... use adapter ...
        await adapter.close()

    Table names are logical (e.g., "document_chunks") and adapters
    map them to physical storage as needed.
    """

    async def initialize(self) -> None:
        """Initialize the adapter and ensure tables exist.

        This method must be idempotent - calling it multiple times
        should have the same effect as calling it once.

        Raises:
            ConnectionError: If unable to connect to backend
            RuntimeError: If initialization fails
        """
        ...

    async def close(self) -> None:
        """Close connections and release resources.

        Should be safe to call multiple times.
        """
        ...

    async def add(
        self,
        table: str,
        records: Sequence[Dict[str, Any]],
    ) -> None:
        """Add records to a table.

        Args:
            table: Logical table name
            records: Records to add (must include 'id' field)

        Raises:
            ValueError: If records are invalid
            RuntimeError: If operation fails
        """
        ...

    async def delete(
        self,
        table: str,
        ids: Sequence[str],
    ) -> int:
        """Delete records by ID.

        Args:
            table: Logical table name
            ids: Record IDs to delete

        Returns:
            Number of records deleted

        Raises:
            RuntimeError: If operation fails
        """
        ...

    async def get_by_ids(
        self,
        table: str,
        ids: Sequence[str],
    ) -> List[Dict[str, Any]]:
        """Retrieve records by ID.

        Args:
            table: Logical table name
            ids: Record IDs to retrieve

        Returns:
            List of records (may be fewer than requested if not found)

        Raises:
            RuntimeError: If operation fails
        """
        ...

    async def upsert(
        self,
        table: str,
        records: Sequence[Dict[str, Any]],
        key_field: str = "id",
    ) -> None:
        """Insert or update records.

        If a record with the same key exists, update it.
        Otherwise, insert a new record.

        Args:
            table: Logical table name
            records: Records to upsert
            key_field: Field to use as unique key (default: "id")

        Raises:
            ValueError: If records are invalid
            RuntimeError: If operation fails
        """
        ...

    async def execute(
        self,
        spec: QuerySpec,
    ) -> List[SearchResult]:
        """Execute a query specification.

        This is the primary query method. The QuerySpec captures
        the application's intent (filters, pagination, sorting)
        and the adapter translates it to backend-specific operations.

        For filter-only queries, returns results with score=1.0.

        Args:
            spec: Query specification

        Returns:
            List of SearchResult with normalized scores (0.0-1.0)

        Raises:
            ValueError: If query spec is invalid
            RuntimeError: If query execution fails
        """
        ...

    async def table_exists(self, table: str) -> bool:
        """Check if a table exists.

        Args:
            table: Logical table name

        Returns:
            True if table exists
        """
        ...

    async def count(
        self,
        table: str,
        filters: Optional[Filter] = None,
    ) -> int:
        """Count records matching filters.

        Args:
            table: Logical table name
            filters: Optional filter criteria

        Returns:
            Number of matching records

        Raises:
            RuntimeError: If operation fails
        """
        ...


# =============================================================================
# Search Capabilities (Optional)
# =============================================================================


@runtime_checkable
class VectorSearchCapability(Protocol):
    """Vector similarity search capability.

    Adapters supporting vector search should implement this protocol.
    The search returns raw results; score normalization happens at the boundary.
    """

    async def vector_search(
        self,
        table: str,
        vector: List[float],
        limit: int = 10,
        filters: Optional[Filter] = None,
        vector_column: str = "vector",
        project_ids: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """Perform vector similarity search.

        Args:
            table: Logical table name
            vector: Query vector
            limit: Maximum results to return
            filters: Optional additional filters
            vector_column: Column containing vectors
            project_ids: Optional project scope

        Returns:
            List of SearchResult with normalized scores (0.0-1.0)
            sorted by similarity (highest first)

        Raises:
            ValueError: If vector dimensions don't match
            RuntimeError: If search fails
        """
        ...


@runtime_checkable
class FTSCapability(Protocol):
    """Full-text search capability.

    Adapters supporting FTS should implement this protocol.
    """

    async def fts_search(
        self,
        table: str,
        query: str,
        limit: int = 10,
        filters: Optional[Filter] = None,
        fts_columns: Optional[List[str]] = None,
        project_ids: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """Perform full-text search.

        Args:
            table: Logical table name
            query: Search query string
            limit: Maximum results to return
            filters: Optional additional filters
            fts_columns: Columns to search (None = table default)
            project_ids: Optional project scope

        Returns:
            List of SearchResult with normalized scores (0.0-1.0)
            sorted by relevance (highest first)

        Raises:
            ValueError: If query is invalid
            RuntimeError: If search fails
        """
        ...


@runtime_checkable
class HybridSearchCapability(Protocol):
    """Native hybrid search capability.

    Adapters with native hybrid search (vector + FTS combined)
    should implement this protocol. If not supported, the app
    layer handles separate searches and merging.
    """

    async def hybrid_search(
        self,
        table: str,
        vector: List[float],
        query: str,
        limit: int = 10,
        filters: Optional[Filter] = None,
        vector_column: str = "vector",
        fts_columns: Optional[List[str]] = None,
        vector_weight: float = 0.7,
        fts_weight: float = 0.3,
        project_ids: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """Perform native hybrid search combining vector and FTS.

        This is optional - backends that don't support native hybrid
        should NOT implement this. The app layer will handle merging.

        Args:
            table: Logical table name
            vector: Query vector
            query: FTS query string
            limit: Maximum results to return
            filters: Optional additional filters
            vector_column: Column containing vectors
            fts_columns: Columns to search (None = table default)
            vector_weight: Weight for vector results (0.0-1.0)
            fts_weight: Weight for FTS results (0.0-1.0)
            project_ids: Optional project scope

        Returns:
            List of SearchResult with normalized scores (0.0-1.0)

        Raises:
            ValueError: If parameters are invalid
            RuntimeError: If search fails
        """
        ...


@runtime_checkable
class GraphRankingCapability(Protocol):
    """Graph-based ranking capability.

    Adapters supporting graph metrics (PageRank, betweenness)
    for result boosting should implement this protocol.
    """

    async def has_graph_ranking(self, table: str) -> bool:
        """Check if graph ranking is available for a table.

        Args:
            table: Logical table name

        Returns:
            True if graph ranking metrics are available
        """
        ...

    async def apply_graph_boost(
        self,
        results: List[SearchResult],
        table: str,
        boost_factor: float = 0.1,
    ) -> List[SearchResult]:
        """Apply graph-based score boosting to results.

        Boosts results based on PageRank or other graph metrics.
        The boost_factor determines how much graph metrics influence
        the final score.

        Args:
            results: Search results to boost
            table: Source table (for looking up graph metrics)
            boost_factor: How much to weight graph metrics (0.0-1.0)

        Returns:
            Results with adjusted scores (still normalized 0.0-1.0)
        """
        ...


# =============================================================================
# Batch Operations (Optional)
# =============================================================================


@runtime_checkable
class BatchCapability(Protocol):
    """Batch operation capability for bulk operations.

    Adapters supporting efficient bulk operations should implement this.
    """

    async def add_batch(
        self,
        table: str,
        records: Sequence[Dict[str, Any]],
        batch_size: int = 1000,
    ) -> int:
        """Add records in batches.

        More efficient than add() for large record sets.

        Args:
            table: Logical table name
            records: Records to add
            batch_size: Records per batch

        Returns:
            Total number of records added

        Raises:
            RuntimeError: If operation fails
        """
        ...

    async def delete_batch(
        self,
        table: str,
        filters: Filter,
        batch_size: int = 1000,
    ) -> int:
        """Delete records matching filters in batches.

        Args:
            table: Logical table name
            filters: Filter criteria for deletion
            batch_size: Records per batch

        Returns:
            Total number of records deleted

        Raises:
            RuntimeError: If operation fails
        """
        ...


# =============================================================================
# Transaction Support (Optional)
# =============================================================================


@runtime_checkable
class TransactionCapability(Protocol):
    """Transaction support for atomic operations.

    Adapters supporting transactions should implement this.
    """

    async def begin_transaction(self) -> Any:
        """Begin a new transaction.

        Returns:
            Transaction handle (implementation-specific)
        """
        ...

    async def commit_transaction(self, transaction: Any) -> None:
        """Commit a transaction.

        Args:
            transaction: Transaction handle from begin_transaction
        """
        ...

    async def rollback_transaction(self, transaction: Any) -> None:
        """Rollback a transaction.

        Args:
            transaction: Transaction handle from begin_transaction
        """
        ...


# =============================================================================
# Capability Detection Helpers
# =============================================================================


def has_vector_search(adapter: VectorStorageProtocol) -> bool:
    """Check if adapter supports vector search.

    Args:
        adapter: Adapter instance to check

    Returns:
        True if adapter implements VectorSearchCapability
    """
    return isinstance(adapter, VectorSearchCapability)


def has_fts(adapter: VectorStorageProtocol) -> bool:
    """Check if adapter supports full-text search.

    Args:
        adapter: Adapter instance to check

    Returns:
        True if adapter implements FTSCapability
    """
    return isinstance(adapter, FTSCapability)


def has_hybrid_search(adapter: VectorStorageProtocol) -> bool:
    """Check if adapter supports native hybrid search.

    Args:
        adapter: Adapter instance to check

    Returns:
        True if adapter implements HybridSearchCapability
    """
    return isinstance(adapter, HybridSearchCapability)


def has_graph_ranking(adapter: VectorStorageProtocol) -> bool:
    """Check if adapter supports graph-based ranking.

    Args:
        adapter: Adapter instance to check

    Returns:
        True if adapter implements GraphRankingCapability
    """
    return isinstance(adapter, GraphRankingCapability)


def has_batch(adapter: VectorStorageProtocol) -> bool:
    """Check if adapter supports batch operations.

    Args:
        adapter: Adapter instance to check

    Returns:
        True if adapter implements BatchCapability
    """
    return isinstance(adapter, BatchCapability)


def has_transactions(adapter: VectorStorageProtocol) -> bool:
    """Check if adapter supports transactions.

    Args:
        adapter: Adapter instance to check

    Returns:
        True if adapter implements TransactionCapability
    """
    return isinstance(adapter, TransactionCapability)


# =============================================================================
# Indexing Database Protocol (Domain-Specific)
# =============================================================================


@runtime_checkable
class IndexingDatabaseProtocol(Protocol):
    """Protocol for database operations used by the indexing pipeline.

    This protocol defines the high-level database operations required for
    indexing documents, entities, and relationships. It abstracts the
    underlying storage mechanism, enabling different backend implementations.

    Unlike VectorStorageProtocol which is generic, this protocol is specific
    to the indexing domain and uses domain types (DocumentChunk, GraphEntity,
    GraphRelationship).

    Design:
        - DES-S2-001 in .sessions/deep-architecture-review/009-design.md
    """

    async def upsert_chunks(
        self,
        chunks: Sequence["DocumentChunk"],
        project_id: str,
    ) -> int:
        """Insert or update document chunks.

        If a chunk with the same ID exists, update it. Otherwise, insert it.

        Args:
            chunks: Document chunks to upsert
            project_id: Project identifier for data isolation

        Returns:
            Number of chunks upserted

        Raises:
            ValueError: If chunks are invalid
            RuntimeError: If operation fails
        """
        ...

    async def upsert_entities(
        self,
        entities: Sequence["GraphEntity"],
        project_id: str,
    ) -> int:
        """Insert or update graph entities.

        If an entity with the same ID exists, update it. Otherwise, insert it.

        Args:
            entities: Graph entities to upsert
            project_id: Project identifier for data isolation

        Returns:
            Number of entities upserted

        Raises:
            ValueError: If entities are invalid
            RuntimeError: If operation fails
        """
        ...

    async def upsert_relationships(
        self,
        relationships: Sequence["GraphRelationship"],
        project_id: str,
    ) -> int:
        """Insert or update graph relationships.

        If a relationship with the same ID exists, update it. Otherwise, insert it.

        Args:
            relationships: Graph relationships to upsert
            project_id: Project identifier for data isolation

        Returns:
            Number of relationships upserted

        Raises:
            ValueError: If relationships are invalid
            RuntimeError: If operation fails
        """
        ...

    async def delete_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> int:
        """Delete all data associated with a file.

        Removes document chunks, graph entities, and graph relationships
        that were created from the specified file.

        Args:
            file_path: Path to the source file
            project_id: Project identifier for data isolation

        Returns:
            Total number of records deleted (chunks + entities + relationships)

        Raises:
            RuntimeError: If operation fails
        """
        ...


def has_indexing_support(adapter: object) -> bool:
    """Check if adapter supports indexing operations.

    Args:
        adapter: Adapter instance to check

    Returns:
        True if adapter implements IndexingDatabaseProtocol
    """
    return isinstance(adapter, IndexingDatabaseProtocol)
