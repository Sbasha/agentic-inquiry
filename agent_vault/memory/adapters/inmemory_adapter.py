"""In-memory memory storage adapter.

This adapter provides a non-persistent memory storage implementation
for use when LanceDB is not available (e.g., PostgreSQL backend tests).
Memory items are stored in RAM and lost when the process exits.

This is a temporary solution until proper PostgreSQL memory adapters
are implemented.
"""

import logging
from typing import Any, Dict, List, Optional

from agent_vault.memory.protocols import MemoryStorageProtocol
from agent_vault.memory.models import MemoryItem

logger = logging.getLogger(__name__)


class InMemoryMemoryAdapter(MemoryStorageProtocol):
    """In-memory implementation of memory storage.

    Stores memory items in a dictionary without persistence.
    Useful for testing or when LanceDB is not available.

    Warning:
        All stored memories are lost when the process exits.
        This is NOT suitable for production use.
    """

    def __init__(self, embedding_dims: int = 384):
        """Initialize in-memory adapter.

        Args:
            embedding_dims: Dimension of embedding vectors (for validation)
        """
        self._embedding_dims = embedding_dims
        self._items: Dict[str, tuple[MemoryItem, List[float]]] = {}
        self._initialized = False
        logger.warning(
            "Using InMemoryMemoryAdapter - memories will NOT be persisted! "
            "This is for non-LanceDB backends where PostgreSQL memory adapter "
            "is not yet implemented."
        )

    async def initialize(self) -> None:
        """Initialize the in-memory storage."""
        if self._initialized:
            return
        self._items.clear()
        self._initialized = True
        logger.debug("InMemoryMemoryAdapter initialized")

    async def store(
        self,
        item: MemoryItem,
        vector: List[float],
    ) -> str:
        """Store memory item in memory.

        Args:
            item: Memory item to store
            vector: Embedding vector

        Returns:
            ID of the stored item
        """
        if len(vector) != self._embedding_dims:
            logger.warning(
                "Vector dimension mismatch: expected %d, got %d",
                self._embedding_dims,
                len(vector),
            )
        self._items[item.id] = (item, vector)
        return item.id

    async def retrieve(
        self,
        query_vector: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryItem]:
        """Retrieve memories by vector similarity.

        Uses simple cosine similarity for in-memory search.

        Args:
            query_vector: Query embedding vector
            limit: Maximum results
            filters: Optional filters (basic field matching)

        Returns:
            List of similar memory items
        """
        if not self._items:
            return []

        # Simple cosine similarity
        def cosine_similarity(v1: List[float], v2: List[float]) -> float:
            dot_product = sum(a * b for a, b in zip(v1, v2))
            norm1 = sum(a * a for a in v1) ** 0.5
            norm2 = sum(b * b for b in v2) ** 0.5
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return dot_product / (norm1 * norm2)

        # Score all items
        scored = []
        for item_id, (item, vector) in self._items.items():
            # Apply filters
            if filters:
                skip = False
                for key, value in filters.items():
                    item_value = getattr(item, key, None)
                    if item_value != value:
                        skip = True
                        break
                if skip:
                    continue

            score = cosine_similarity(query_vector, vector)
            scored.append((score, item))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        return [item for score, item in scored[:limit]]

    async def get_by_id(
        self,
        item_id: str,
    ) -> Optional[MemoryItem]:
        """Get memory item by ID.

        Args:
            item_id: Item ID

        Returns:
            Memory item or None
        """
        entry = self._items.get(item_id)
        return entry[0] if entry else None

    async def update(
        self,
        item_id: str,
        updates: Dict[str, Any],
    ) -> bool:
        """Update memory item fields.

        Args:
            item_id: Item ID
            updates: Field updates

        Returns:
            True if updated
        """
        entry = self._items.get(item_id)
        if not entry:
            return False

        item, vector = entry
        # Update item fields directly (MemoryItem is a dataclass)
        for key, value in updates.items():
            if hasattr(item, key):
                setattr(item, key, value)
        return True

    async def delete(
        self,
        item_id: str,
    ) -> bool:
        """Delete memory item.

        Args:
            item_id: Item ID

        Returns:
            True if deleted
        """
        if item_id in self._items:
            del self._items[item_id]
            return True
        return False

    async def count(
        self,
        filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Count memory items.

        Args:
            filters: Optional filters

        Returns:
            Count of matching items
        """
        if not filters:
            return len(self._items)

        count = 0
        for item, _ in self._items.values():
            match = True
            for key, value in filters.items():
                if getattr(item, key, None) != value:
                    match = False
                    break
            if match:
                count += 1
        return count
