"""Protocol definitions for memory storage abstraction.

This module defines the capability-based protocols that memory storage adapters
implement. Protocols use structural subtyping (duck typing) with runtime checking.

Design principles:
- Minimal surface area: Only methods that vary across backends
- Capability-based: Check capabilities at runtime with isinstance()
- Canonical types: All methods use MemoryItem and standard Python types
- Async-only: All I/O operations are async

See: DES-S2-002 in .sessions/deep-architecture-review/009-design.md
"""
from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    Tuple,
    runtime_checkable,
)

if TYPE_CHECKING:
    from agentic_inquiry.memory.models import MemoryItem


# =============================================================================
# Core Memory Storage Protocol
# =============================================================================


@runtime_checkable
class MemoryStorageProtocol(Protocol):
    """Protocol for memory tier persistence.

    This protocol abstracts the storage operations for memory items,
    enabling different backend implementations (LanceDB, PostgreSQL, etc.).

    The protocol focuses on high-level memory operations rather than
    raw database operations. Adapters implementing this protocol
    translate these operations to backend-specific calls.

    Example:
        class LanceDBMemoryAdapter:
            async def store(self, item: MemoryItem, vector: List[float]) -> str:
                # Convert to row format and call LanceDBManager.add_rows
                ...

    Lifecycle:
        adapter = LanceDBMemoryAdapter(db_manager, table_name)
        await adapter.initialize()  # Ensure table exists
        # ... use adapter ...
    """

    async def initialize(self) -> None:
        """Initialize the storage and ensure tables exist.

        This method must be idempotent - calling it multiple times
        should have the same effect as calling it once.

        Raises:
            ConnectionError: If unable to connect to backend
            RuntimeError: If initialization fails
        """
        ...

    async def store(
        self,
        item: "MemoryItem",
        vector: List[float],
    ) -> str:
        """Store memory item with embedding vector.

        Args:
            item: Memory item to store (must have valid id)
            vector: Embedding vector for similarity search

        Returns:
            ID of the stored item

        Raises:
            ValueError: If item is invalid
            RuntimeError: If storage fails
        """
        ...

    async def replace(
        self,
        item: "MemoryItem",
        vector: List[float],
    ) -> None:
        """Write item over any stored item with the same id, in one atomic write.

        The stored item is never absent in between, so a cancelled or failed
        replace leaves either the old or the new version readable.

        Args:
            item: Memory item to write (must have valid id)
            vector: Embedding vector for similarity search

        Raises:
            RuntimeError: If storage fails
        """
        ...

    async def retrieve(
        self,
        query_vector: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List["MemoryItem"]:
        """Retrieve memories by vector similarity.

        Args:
            query_vector: Query embedding vector
            limit: Maximum number of results to return
            filters: Optional field-based filters (e.g., {"tier": "episodic"})

        Returns:
            List of memory items sorted by similarity (highest first)

        Raises:
            ValueError: If query vector dimensions don't match
            RuntimeError: If retrieval fails
        """
        ...

    async def get_by_id(
        self,
        item_id: str,
    ) -> Optional["MemoryItem"]:
        """Retrieve a single memory item by ID.

        Args:
            item_id: ID of the item to retrieve

        Returns:
            Memory item if found, None otherwise

        Raises:
            RuntimeError: If retrieval fails
        """
        ...

    async def update(
        self,
        item_id: str,
        updates: Dict[str, Any],
    ) -> bool:
        """Update memory item fields.

        Only updates the specified fields, preserving other values.

        Args:
            item_id: ID of the item to update
            updates: Dictionary of field: value pairs to update

        Returns:
            True if item was updated, False if not found

        Raises:
            ValueError: If updates contain invalid fields
            RuntimeError: If update fails
        """
        ...

    async def delete(
        self,
        item_id: str,
    ) -> bool:
        """Delete memory item.

        Args:
            item_id: ID of the item to delete

        Returns:
            True if item was deleted, False if not found

        Raises:
            RuntimeError: If deletion fails
        """
        ...

    async def count(
        self,
        filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Count memory items matching filters.

        Args:
            filters: Optional field-based filters

        Returns:
            Number of matching items

        Raises:
            RuntimeError: If count fails
        """
        ...


# =============================================================================
# Bulk Operations Capability (Optional)
# =============================================================================


@runtime_checkable
class MemoryBulkCapability(Protocol):
    """Optional capability for bulk memory operations.

    Adapters supporting efficient bulk operations should implement this.
    """

    async def store_batch(
        self,
        items: List["MemoryItem"],
        vectors: List[List[float]],
    ) -> int:
        """Store multiple memory items in a batch.

        More efficient than calling store() repeatedly.

        Args:
            items: Memory items to store
            vectors: Corresponding embedding vectors (same order as items)

        Returns:
            Number of items stored

        Raises:
            ValueError: If items and vectors lengths don't match
            RuntimeError: If storage fails
        """
        ...

    async def delete_batch(
        self,
        item_ids: List[str],
    ) -> int:
        """Delete multiple memory items.

        Args:
            item_ids: IDs of items to delete

        Returns:
            Number of items deleted

        Raises:
            RuntimeError: If deletion fails
        """
        ...


# =============================================================================
# Query Capability (Optional)
# =============================================================================


@runtime_checkable
class MemoryQueryCapability(Protocol):
    """Optional capability for advanced querying.

    Adapters supporting SQL-like filtering should implement this.
    """

    async def query(
        self,
        filters: Dict[str, Any],
        limit: Optional[int] = None,
        offset: int = 0,
        order_by: Optional[str] = None,
        order_desc: bool = False,
    ) -> List["MemoryItem"]:
        """Query memory items with advanced filtering.

        Args:
            filters: Field-based filter conditions
            limit: Maximum results to return (None = all)
            offset: Number of results to skip
            order_by: Field name to sort by
            order_desc: Sort descending if True

        Returns:
            List of matching memory items

        Raises:
            ValueError: If filters or order_by are invalid
            RuntimeError: If query fails
        """
        ...


# =============================================================================
# Scored Retrieval Capability (Optional)
# =============================================================================


@runtime_checkable
class MemoryScoredRetrievalCapability(Protocol):
    """Optional capability for retrieval with similarity scores.

    Adapters that can return similarity/distance scores should implement this.
    Memory layers use this to populate relevance_score in RetrievalResult.
    """

    async def retrieve_with_scores(
        self,
        query_vector: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple["MemoryItem", float]]:
        """Retrieve memories by vector similarity with scores.

        Args:
            query_vector: Query embedding vector
            limit: Maximum number of results to return
            filters: Optional field-based filters

        Returns:
            List of (MemoryItem, similarity_score) tuples sorted by similarity
            Similarity scores are in range [0, 1] where 1 is most similar.

        Raises:
            ValueError: If query vector dimensions don't match
            RuntimeError: If retrieval fails
        """
        ...


# =============================================================================
# Capability Detection Helpers
# =============================================================================


def has_bulk_capability(adapter: MemoryStorageProtocol) -> bool:
    """Check if adapter supports bulk operations.

    Args:
        adapter: Adapter instance to check

    Returns:
        True if adapter implements MemoryBulkCapability
    """
    return isinstance(adapter, MemoryBulkCapability)


def has_query_capability(adapter: MemoryStorageProtocol) -> bool:
    """Check if adapter supports advanced querying.

    Args:
        adapter: Adapter instance to check

    Returns:
        True if adapter implements MemoryQueryCapability
    """
    return isinstance(adapter, MemoryQueryCapability)


def has_scored_retrieval(adapter: MemoryStorageProtocol) -> bool:
    """Check if adapter supports retrieval with similarity scores.

    Args:
        adapter: Adapter instance to check

    Returns:
        True if adapter implements MemoryScoredRetrievalCapability
    """
    return isinstance(adapter, MemoryScoredRetrievalCapability)
