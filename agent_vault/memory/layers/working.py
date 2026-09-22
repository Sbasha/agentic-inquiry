"""
Working Memory implementation.

Provides high-speed in-memory cache for current session context with LRU eviction.
"""

import logging
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

import numpy as np

from agent_vault.memory.models import MemoryContext, MemoryItem, MemoryTier, RetrievalResult

logger = logging.getLogger(__name__)


class WorkingMemory:
    """
    High-speed in-memory cache for current session context.

    Uses LRU (Least Recently Used) eviction policy when capacity is reached.
    All items are session-scoped and can be cleared on session termination.
    """

    def __init__(self, capacity: int = 20) -> None:
        """
        Initialize WorkingMemory.

        Args:
            capacity: Maximum number of items to store (default: 20)
        """
        self.capacity = capacity
        # OrderedDict maintains insertion order and supports move_to_end for LRU
        self._storage: OrderedDict[str, MemoryItem] = OrderedDict()
        logger.info("WorkingMemory initialized with capacity=%d", capacity)

    def _evict_lru(self) -> None:
        """
        Evict the least recently used item.

        Removes the oldest item from storage when capacity is reached.
        """
        if self._storage:
            evicted_id, evicted_item = self._storage.popitem(last=False)
            logger.debug(
                "Evicted LRU item: id=%s, session=%s",
                evicted_id,
                evicted_item.context.session_id,
            )

    async def store(self, item: MemoryItem) -> None:
        """
        Store a memory item in working memory.

        If capacity is reached, evicts the least recently used item.
        Updates existing items if the same ID is stored again.

        Args:
            item: MemoryItem to store
        """
        # Check capacity and evict if necessary
        if item.id not in self._storage and len(self._storage) >= self.capacity:
            self._evict_lru()

        # Store or update item
        self._storage[item.id] = item
        # Move to end to mark as most recently used
        self._storage.move_to_end(item.id)

        logger.debug(
            "Stored item in working memory: id=%s, agent=%s, session=%s",
            item.id,
            item.context.agent_id,
            item.context.session_id,
        )

    async def get_by_id(self, item_id: str) -> MemoryItem | None:
        """
        Retrieve a single memory item by ID.

        Updates access statistics and moves item to end (most recently used).

        Args:
            item_id: Unique identifier of the memory item

        Returns:
            MemoryItem if found, None otherwise
        """
        item = self._storage.get(item_id)
        if item:
            # Update access statistics
            item.access()
            # Move to end to mark as most recently used
            self._storage.move_to_end(item_id)
            logger.debug("Retrieved item from working memory: id=%s", item_id)
        return item

    async def delete(self, item_id: str) -> bool:
        """
        Delete a memory item by ID.

        Args:
            item_id: Unique identifier of the memory item

        Returns:
            True if item was deleted, False if not found
        """
        if item_id in self._storage:
            del self._storage[item_id]
            logger.debug("Deleted item from working memory: id=%s", item_id)
            return True
        return False

    async def clear_session(self, session_id: str) -> int:
        """
        Remove all items associated with a session ID.

        Args:
            session_id: Session identifier

        Returns:
            Number of items removed
        """
        items_to_remove = [
            item_id
            for item_id, item in self._storage.items()
            if item.context.session_id == session_id
        ]

        for item_id in items_to_remove:
            del self._storage[item_id]

        count = len(items_to_remove)
        logger.info("Cleared session from working memory: session=%s, count=%d", session_id, count)
        return count

    async def retrieve(
        self,
        query_embedding: np.ndarray,
        context: MemoryContext,
        limit: int = 10,
    ) -> list[RetrievalResult]:
        """
        Retrieve memory items using vector similarity search.

        Filters by agent_id and session_id from context, then ranks by
        cosine similarity to the query embedding.

        Args:
            query_embedding: Query vector for similarity search
            context: Memory context for filtering
            limit: Maximum number of results to return

        Returns:
            List of RetrievalResult objects ranked by relevance
        """
        results: list[RetrievalResult] = []
        retrieval_time = datetime.now(timezone.utc)

        # Filter items by context
        filtered_items = [
            item
            for item in self._storage.values()
            if item.context.agent_id == context.agent_id
            and item.context.session_id == context.session_id
            and item.embedding is not None
        ]

        # Calculate similarity scores
        for item in filtered_items:
            if item.embedding is None:
                continue

            # Cosine similarity
            similarity = float(
                np.dot(query_embedding, item.embedding)
                / (np.linalg.norm(query_embedding) * np.linalg.norm(item.embedding))
            )

            results.append(
                RetrievalResult(
                    item=item,
                    relevance_score=similarity,
                    retrieval_tier=MemoryTier.WORKING,
                    retrieval_time=retrieval_time,
                )
            )

            # Update access statistics
            item.access()
            # Move to end to mark as most recently used
            self._storage.move_to_end(item.id)

        # Sort by relevance score (descending) and limit
        results.sort(key=lambda r: r.relevance_score, reverse=True)
        results = results[:limit]

        logger.debug(
            "Retrieved %d items from working memory for agent=%s, session=%s",
            len(results),
            context.agent_id,
            context.session_id,
        )

        return results

    async def get_all_items(
        self, context: MemoryContext | None = None
    ) -> list[MemoryItem]:
        """
        Get all memory items, optionally filtered by context.

        Args:
            context: Optional context for filtering by agent_id and session_id

        Returns:
            List of all matching MemoryItem objects
        """
        if context is None:
            return list(self._storage.values())

        # Filter by context
        filtered_items = [
            item
            for item in self._storage.values()
            if item.context.agent_id == context.agent_id
            and item.context.session_id == context.session_id
        ]

        logger.debug(
            "Retrieved all items from working memory: count=%d, filtered=%s",
            len(filtered_items),
            context is not None,
        )

        return filtered_items

    def get_stats(self) -> dict[str, Any]:
        """
        Get statistics about working memory.

        Returns:
            Dictionary with capacity, current size, and utilization
        """
        return {
            "capacity": self.capacity,
            "size": len(self._storage),
            "utilization": len(self._storage) / self.capacity if self.capacity > 0 else 0.0,
        }
