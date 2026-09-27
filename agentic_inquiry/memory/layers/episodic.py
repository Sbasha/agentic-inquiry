"""
Episodic Memory implementation.

Provides persistent time-series event storage with vector search.

Uses MemoryStorageProtocol for storage operations, enabling backend swappability.
The protocol-based design allows different storage backends (LanceDB, PostgreSQL, etc.)
to be used without changing the memory layer logic.

Example:
    from agentic_inquiry.memory.adapters import LanceDBMemoryAdapter
    from agentic_inquiry.memory.protocols import MemoryStorageProtocol

    adapter = LanceDBMemoryAdapter(db_manager, "memory_episodic", dims=384)
    await adapter.initialize()
    episodic = EpisodicMemory(adapter)
    await episodic.initialize()
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import cast

import numpy as np

from agentic_inquiry.memory.models import MemoryContext, MemoryItem, MemoryTier, RetrievalResult
from agentic_inquiry.memory.protocols import (
    MemoryStorageProtocol,
    MemoryScoredRetrievalCapability,
    has_scored_retrieval,
)

logger = logging.getLogger(__name__)


class EpisodicMemory:
    """
    Persistent time-series event storage with vector search.

    Uses MemoryStorageProtocol for storage operations. Supports timestamp-based
    indexing and emotional metadata for episodic memories.

    Episodic memory prioritizes recency and context over pure semantic similarity,
    making it suitable for storing event-based memories that are time-sensitive.
    """

    def __init__(
        self,
        storage: MemoryStorageProtocol,
        limit: int = 1000,
    ) -> None:
        """
        Initialize EpisodicMemory.

        Args:
            storage: Memory storage adapter implementing MemoryStorageProtocol.
                     Use LanceDBMemoryAdapter for LanceDB-backed storage.
            limit: Maximum number of items to store (default: 1000)

        Raises:
            TypeError: If storage doesn't implement MemoryStorageProtocol
        """
        if not isinstance(storage, MemoryStorageProtocol):
            raise TypeError(
                f"storage must implement MemoryStorageProtocol, got {type(storage).__name__}"
            )

        self._storage = storage
        self.limit = limit
        self._tier_name = "episodic"

        # Check if storage supports scored retrieval
        self._has_scored_retrieval = has_scored_retrieval(storage)

        self._initialized = False
        logger.info(
            "EpisodicMemory initialized: limit=%d, scored_retrieval=%s",
            self.limit,
            self._has_scored_retrieval,
        )

    async def initialize(self) -> None:
        """
        Initialize the storage adapter.

        Delegates to the storage adapter's initialize method which handles
        database connection and table creation.
        """
        if self._initialized:
            return

        # Initialize the storage adapter
        await self._storage.initialize()

        self._initialized = True
        logger.info("EpisodicMemory initialized successfully")

    async def store(self, item: MemoryItem) -> None:
        """
        Store a memory item in episodic memory.

        Args:
            item: MemoryItem to store
        """
        if not self._initialized:
            await self.initialize()

        # Evict oldest items if at capacity
        current_count = await self._storage.count()
        if current_count >= self.limit:
            evict_count = current_count - self.limit + 1
            # Retrieve oldest items using zero vector (timestamp-sorted by adapter)
            oldest = await self._storage.retrieve(
                query_vector=[0.0] * 384,
                limit=evict_count,
            )
            for old_item in oldest:
                await self._storage.delete(old_item.id)
            logger.debug("Evicted %d oldest items (capacity: %d)", len(oldest), self.limit)

        # Get embedding vector from item
        vector = item.embedding.tolist() if item.embedding is not None else []

        # Delegate to storage adapter
        await self._storage.store(item, vector)

        logger.debug(
            "Stored item in episodic memory: id=%s, agent=%s, session=%s",
            item.id,
            item.context.agent_id,
            item.context.session_id,
        )

    async def get_by_id(self, item_id: str, update_access: bool = True) -> MemoryItem | None:
        """
        Retrieve a single memory item by ID.

        Args:
            item_id: Unique identifier of the memory item
            update_access: Whether to update access statistics (default: True)

        Returns:
            MemoryItem if found, None otherwise
        """
        if not self._initialized:
            await self.initialize()

        # Delegate to storage adapter
        item = await self._storage.get_by_id(item_id)

        if item is None:
            return None

        # Update access statistics if requested
        if update_access:
            await self._record_access(item)

        logger.debug("Retrieved item from episodic memory: id=%s", item_id)
        return item

    async def update(self, item: MemoryItem) -> None:
        """
        Update an existing memory item.

        Replaces the item entirely (delete + store) to ensure all fields
        including the embedding vector are updated.

        Args:
            item: MemoryItem with updated values
        """
        if not self._initialized:
            await self.initialize()

        # Delete old version and insert updated version
        await self._storage.delete(item.id)

        # Insert updated version
        vector = item.embedding.tolist() if item.embedding is not None else []
        await self._storage.store(item, vector)

        logger.debug("Updated item in episodic memory: id=%s", item.id)

    async def update_fields(self, item_id: str, updates: dict[str, object]) -> bool:
        """
        Set scalar fields of a stored item without rewriting the rest of it.

        Use this rather than update() when changing a score or status, so a
        concurrent writer of other fields (such as access statistics) is not
        overwritten.

        Args:
            item_id: Unique identifier of the memory item
            updates: MemoryItem field name to new value

        Returns:
            True if the item was found and updated, False otherwise
        """
        if not self._initialized:
            await self.initialize()

        return await self._storage.update(item_id, updates)

    async def _record_access(self, item: MemoryItem) -> None:
        """Count an access on item and persist only its access fields."""
        item.access()
        await self._storage.update(
            item.id,
            {"access_count": item.access_count, "accessed_at": item.accessed_at},
        )

    async def delete(self, item_id: str) -> bool:
        """
        Delete a memory item by ID.

        Args:
            item_id: Unique identifier of the memory item

        Returns:
            True if item was deleted, False if not found
        """
        if not self._initialized:
            await self.initialize()

        # Delegate to storage adapter
        deleted = await self._storage.delete(item_id)

        if deleted:
            logger.debug("Deleted item from episodic memory: id=%s", item_id)

        return deleted

    async def retrieve(
        self,
        query_embedding: np.ndarray,
        context: MemoryContext,
        limit: int = 10,
        query_text: str | None = None,
    ) -> list[RetrievalResult]:
        """
        Retrieve memory items using vector similarity search.

        Filters by agent_id from context, then ranks by similarity.
        Results are sorted by timestamp for recency (episodic memory
        prioritizes recency/context over pure semantic similarity).

        When the storage adapter supports server-side embedding (AlloyDB, RDS)
        and query_text is provided, uses the database's embedding() function
        for the query instead of the pre-computed query_embedding vector.

        Args:
            query_embedding: Query vector for similarity search
            context: Memory context for filtering
            limit: Maximum number of results to return
            query_text: Original query string for server-side embedding (optional)

        Returns:
            List of RetrievalResult objects ranked by relevance and recency
        """
        if not self._initialized:
            await self.initialize()

        retrieval_time = datetime.now(timezone.utc)
        filters = {"agent_id": context.agent_id}

        # Check if storage supports server-side embedding and we have query text
        use_server_side = (
            query_text is not None
            and hasattr(self._storage, 'supports_server_side_embedding')
            and self._storage.supports_server_side_embedding
        )

        # Use scored retrieval if available (preferred)
        if self._has_scored_retrieval:
            scored_storage = cast(MemoryScoredRetrievalCapability, self._storage)

            if use_server_side and hasattr(scored_storage, 'retrieve_with_scores_by_text'):
                results = await scored_storage.retrieve_with_scores_by_text(
                    query_text=query_text,
                    limit=limit * 2,
                    filters=filters,
                )
            else:
                query_vector = query_embedding.tolist()
                results = await scored_storage.retrieve_with_scores(
                    query_vector=query_vector,
                    limit=limit * 2,
                    filters=filters,
                )

            retrieval_results: list[RetrievalResult] = []
            ids_to_update: list[str] = []
            for item, similarity in results:
                retrieval_results.append(
                    RetrievalResult(
                        item=item,
                        relevance_score=similarity,
                        retrieval_tier=MemoryTier.EPISODIC,
                        retrieval_time=retrieval_time,
                    )
                )

                # Collect IDs for access stat update (non-blocking)
                ids_to_update.append(item.id)

            # Fire-and-forget access stat updates — must not block or fail retrieval
            if ids_to_update:
                asyncio.create_task(self._update_access_stats(ids_to_update))
        else:
            # Fall back to basic retrieve (no scores)
            if use_server_side and hasattr(self._storage, 'retrieve_by_text'):
                items = await self._storage.retrieve_by_text(
                    query_text=query_text,
                    limit=limit * 2,
                    filters=filters,
                )
            else:
                query_vector = query_embedding.tolist()
                items = await self._storage.retrieve(
                    query_vector=query_vector,
                    limit=limit * 2,
                    filters=filters,
                )

            retrieval_results = []
            ids_to_update_fallback: list[str] = []
            for item in items:
                retrieval_results.append(
                    RetrievalResult(
                        item=item,
                        relevance_score=0.5,  # Default score when unavailable
                        retrieval_tier=MemoryTier.EPISODIC,
                        retrieval_time=retrieval_time,
                    )
                )

                # Collect IDs for access stat update (non-blocking)
                ids_to_update_fallback.append(item.id)

            # Fire-and-forget access stat updates — must not block or fail retrieval
            if ids_to_update_fallback:
                asyncio.ensure_future(self._update_access_stats(ids_to_update_fallback))

        # Blend similarity and recency for episodic memory ranking.
        # Pure recency sorting overrides semantic relevance; pure similarity
        # ignores temporal context. Blend gives best of both.
        import math
        now = retrieval_time

        def blended_score(r: RetrievalResult) -> float:
            similarity = r.relevance_score  # 0-1 from vector cosine
            # Recency: decay over hours (half-life = 24h)
            age_hours = max(0.001, (now - r.item.created_at).total_seconds() / 3600)
            recency = math.exp(-0.029 * age_hours)  # 0.029 ≈ ln(2)/24
            # 70% similarity, 30% recency
            return (similarity * 0.7) + (recency * 0.3)

        for r in retrieval_results:
            r.relevance_score = blended_score(r)

        retrieval_results.sort(key=lambda r: r.relevance_score, reverse=True)

        # Limit results
        retrieval_results = retrieval_results[:limit]

        logger.debug(
            "Retrieved %d items from episodic memory for agent=%s",
            len(retrieval_results),
            context.agent_id,
        )

        return retrieval_results

    async def _update_access_stats(self, item_ids: list[str]) -> None:
        """Persist access count and accessed_at updates for retrieved items.

        Called as a fire-and-forget task from retrieve() so it never blocks
        the recall path, which means it can overlap the caller's own writes
        (e.g., update_importance). It re-fetches each item for the current
        count and writes only the access fields, so those writes survive.
        All items are updated in parallel via asyncio.gather.
        Failures are logged but do not propagate.

        Args:
            item_ids: IDs of items to refresh and persist access stats for.
        """
        async def _update_one(item_id: str) -> None:
            try:
                fresh_item = await self._storage.get_by_id(item_id)
                if fresh_item is not None:
                    await self._record_access(fresh_item)
            except Exception:
                logger.debug(
                    "Failed to persist access stats for %s item %s",
                    self._tier_name,
                    item_id,
                )

        await asyncio.gather(*[_update_one(iid) for iid in item_ids])

    async def get_all_items(
        self, context: MemoryContext | None = None
    ) -> list[MemoryItem]:
        """
        Get all memory items, optionally filtered by context.

        Args:
            context: Optional context for filtering by agent_id

        Returns:
            List of all matching MemoryItem objects
        """
        if not self._initialized:
            await self.initialize()

        # Build filters
        filters = {"agent_id": context.agent_id} if context is not None else {}

        # Use count to get a reasonable limit and retrieve items
        count = await self._storage.count(filters if filters else None)
        limit = min(count, self.limit) if count > 0 else self.limit

        # Zero vector retrieves all items without similarity bias
        zero_vector = [0.0] * 384  # Default dimension

        items = await self._storage.retrieve(
            query_vector=zero_vector,
            limit=limit,
            filters=filters if filters else None,
        )

        logger.debug(
            "Retrieved all items from episodic memory: count=%d, filtered=%s",
            len(items),
            context is not None,
        )

        return items

    async def get_stats(self) -> dict[str, object]:
        """
        Get statistics about episodic memory.

        Returns:
            Dictionary with capacity, current size, and utilization
        """
        if not self._initialized:
            await self.initialize()

        size = await self._storage.count()

        return {
            "capacity": self.limit,
            "size": size,
            "utilization": size / self.limit if self.limit > 0 else 0.0,
            "has_scored_retrieval": self._has_scored_retrieval,
        }
