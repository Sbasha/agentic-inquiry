"""
Tests for WorkingMemory layer.

Tests in-memory storage, LRU eviction, session clearing, and retrieval operations.
"""

import pytest

pytestmark = pytest.mark.unit

import uuid

import numpy as np

from agentic_inquiry.memory.layers.working import WorkingMemory
from agentic_inquiry.memory.models import MemoryContext, MemoryItem, MemoryTier


@pytest.fixture
def working_memory() -> WorkingMemory:
    """Create a WorkingMemory instance with default capacity."""
    return WorkingMemory(capacity=5)


@pytest.fixture
def memory_context() -> MemoryContext:
    """Create a test memory context."""
    return MemoryContext(
        agent_id="test_agent",
        session_id="test_session",
        conversation_id="test_conversation",
    )


@pytest.fixture
def sample_memory_item(memory_context: MemoryContext) -> MemoryItem:
    """Create a sample memory item."""
    return MemoryItem(
        id=str(uuid.uuid4()),
        content="Test content",
        summary="Test summary",
        context=memory_context,
        importance=0.8,
        tier=MemoryTier.WORKING,
        creator_agent_id="test_agent",
        modifier_agent_id="test_agent",
        embedding=np.random.rand(128).astype(np.float32),
        summary_embedding=np.random.rand(64).astype(np.float32),
    )


@pytest.mark.asyncio
class TestWorkingMemoryStorage:
    """Test storage operations."""

    async def test_store_item(
        self, working_memory: WorkingMemory, sample_memory_item: MemoryItem
    ) -> None:
        """Test storing a single item."""
        await working_memory.store(sample_memory_item)

        # Verify item is stored
        retrieved = await working_memory.get_by_id(sample_memory_item.id)
        assert retrieved is not None
        assert retrieved.id == sample_memory_item.id
        assert retrieved.content == sample_memory_item.content

    async def test_store_multiple_items(
        self, working_memory: WorkingMemory, memory_context: MemoryContext
    ) -> None:
        """Test storing multiple items."""
        items = []
        for i in range(3):
            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=f"Content {i}",
                summary=f"Summary {i}",
                context=memory_context,
                importance=0.5,
                tier=MemoryTier.WORKING,
                creator_agent_id="test_agent",
                modifier_agent_id="test_agent",
                embedding=np.random.rand(128).astype(np.float32),
            )
            items.append(item)
            await working_memory.store(item)

        # Verify all items are stored
        for item in items:
            retrieved = await working_memory.get_by_id(item.id)
            assert retrieved is not None
            assert retrieved.id == item.id

    async def test_update_existing_item(
        self, working_memory: WorkingMemory, sample_memory_item: MemoryItem
    ) -> None:
        """Test updating an existing item."""
        await working_memory.store(sample_memory_item)

        # Update the item
        sample_memory_item.content = "Updated content"
        await working_memory.store(sample_memory_item)

        # Verify update
        retrieved = await working_memory.get_by_id(sample_memory_item.id)
        assert retrieved is not None
        assert retrieved.content == "Updated content"

    async def test_get_by_id_not_found(self, working_memory: WorkingMemory) -> None:
        """Test retrieving non-existent item."""
        result = await working_memory.get_by_id("nonexistent_id")
        assert result is None

    async def test_get_by_id_updates_access(
        self, working_memory: WorkingMemory, sample_memory_item: MemoryItem
    ) -> None:
        """Test that get_by_id updates access statistics."""
        await working_memory.store(sample_memory_item)

        initial_access_count = sample_memory_item.access_count
        initial_accessed_at = sample_memory_item.accessed_at

        # Retrieve item
        await working_memory.get_by_id(sample_memory_item.id)

        # Verify access statistics updated
        assert sample_memory_item.access_count == initial_access_count + 1
        assert sample_memory_item.accessed_at > initial_accessed_at

    async def test_delete_item(
        self, working_memory: WorkingMemory, sample_memory_item: MemoryItem
    ) -> None:
        """Test deleting an item."""
        await working_memory.store(sample_memory_item)

        # Delete item
        result = await working_memory.delete(sample_memory_item.id)
        assert result is True

        # Verify item is deleted
        retrieved = await working_memory.get_by_id(sample_memory_item.id)
        assert retrieved is None

    async def test_delete_nonexistent_item(self, working_memory: WorkingMemory) -> None:
        """Test deleting non-existent item."""
        result = await working_memory.delete("nonexistent_id")
        assert result is False


@pytest.mark.asyncio
class TestWorkingMemoryCapacity:
    """Test capacity management and LRU eviction."""

    async def test_capacity_limit(
        self, working_memory: WorkingMemory, memory_context: MemoryContext
    ) -> None:
        """Test that capacity limit is enforced."""
        # Store items up to capacity (5)
        items = []
        for i in range(5):
            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=f"Content {i}",
                summary=f"Summary {i}",
                context=memory_context,
                importance=0.5,
                tier=MemoryTier.WORKING,
                creator_agent_id="test_agent",
                modifier_agent_id="test_agent",
                embedding=np.random.rand(128).astype(np.float32),
            )
            items.append(item)
            await working_memory.store(item)

        # Verify all items are stored
        stats = working_memory.get_stats()
        assert stats["size"] == 5
        assert stats["utilization"] == 1.0

    async def test_lru_eviction(
        self, working_memory: WorkingMemory, memory_context: MemoryContext
    ) -> None:
        """Test LRU eviction when capacity is exceeded."""
        # Store items up to capacity (5)
        items = []
        for i in range(5):
            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=f"Content {i}",
                summary=f"Summary {i}",
                context=memory_context,
                importance=0.5,
                tier=MemoryTier.WORKING,
                creator_agent_id="test_agent",
                modifier_agent_id="test_agent",
                embedding=np.random.rand(128).astype(np.float32),
            )
            items.append(item)
            await working_memory.store(item)

        # Store one more item to trigger eviction
        new_item = MemoryItem(
            id=str(uuid.uuid4()),
            content="New content",
            summary="New summary",
            context=memory_context,
            importance=0.5,
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(128).astype(np.float32),
        )
        await working_memory.store(new_item)

        # Verify oldest item (items[0]) was evicted
        evicted = await working_memory.get_by_id(items[0].id)
        assert evicted is None

        # Verify new item is stored
        retrieved = await working_memory.get_by_id(new_item.id)
        assert retrieved is not None

        # Verify capacity is maintained
        stats = working_memory.get_stats()
        assert stats["size"] == 5

    async def test_lru_access_updates_order(
        self, working_memory: WorkingMemory, memory_context: MemoryContext
    ) -> None:
        """Test that accessing an item updates its LRU position."""
        # Store items up to capacity (5)
        items = []
        for i in range(5):
            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=f"Content {i}",
                summary=f"Summary {i}",
                context=memory_context,
                importance=0.5,
                tier=MemoryTier.WORKING,
                creator_agent_id="test_agent",
                modifier_agent_id="test_agent",
                embedding=np.random.rand(128).astype(np.float32),
            )
            items.append(item)
            await working_memory.store(item)

        # Access the oldest item (items[0])
        await working_memory.get_by_id(items[0].id)

        # Store one more item to trigger eviction
        new_item = MemoryItem(
            id=str(uuid.uuid4()),
            content="New content",
            summary="New summary",
            context=memory_context,
            importance=0.5,
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(128).astype(np.float32),
        )
        await working_memory.store(new_item)

        # Verify items[0] is still present (was accessed, so not LRU)
        retrieved = await working_memory.get_by_id(items[0].id)
        assert retrieved is not None

        # Verify items[1] was evicted (now the LRU)
        evicted = await working_memory.get_by_id(items[1].id)
        assert evicted is None


@pytest.mark.asyncio
class TestWorkingMemorySession:
    """Test session-based operations."""

    async def test_clear_session(
        self, working_memory: WorkingMemory, memory_context: MemoryContext
    ) -> None:
        """Test clearing all items for a session."""
        # Store items for test session
        for i in range(3):
            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=f"Content {i}",
                summary=f"Summary {i}",
                context=memory_context,
                importance=0.5,
                tier=MemoryTier.WORKING,
                creator_agent_id="test_agent",
                modifier_agent_id="test_agent",
                embedding=np.random.rand(128).astype(np.float32),
            )
            await working_memory.store(item)

        # Store items for different session
        other_context = MemoryContext(
            agent_id="test_agent",
            session_id="other_session",
            conversation_id="other_conversation",
        )
        other_items = []
        for i in range(2):
            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=f"Other content {i}",
                summary=f"Other summary {i}",
                context=other_context,
                importance=0.5,
                tier=MemoryTier.WORKING,
                creator_agent_id="test_agent",
                modifier_agent_id="test_agent",
                embedding=np.random.rand(128).astype(np.float32),
            )
            other_items.append(item)
            await working_memory.store(item)

        # Clear test session
        count = await working_memory.clear_session("test_session")
        assert count == 3

        # Verify test session items are cleared
        all_items = await working_memory.get_all_items()
        assert len(all_items) == 2

        # Verify other session items remain
        for item in other_items:
            retrieved = await working_memory.get_by_id(item.id)
            assert retrieved is not None

    async def test_clear_empty_session(self, working_memory: WorkingMemory) -> None:
        """Test clearing a session with no items."""
        count = await working_memory.clear_session("nonexistent_session")
        assert count == 0


@pytest.mark.asyncio
class TestWorkingMemoryRetrieval:
    """Test retrieval operations."""

    async def test_retrieve_with_similarity(
        self, working_memory: WorkingMemory, memory_context: MemoryContext
    ) -> None:
        """Test vector similarity retrieval."""
        # Create query embedding
        query_embedding = np.random.rand(128).astype(np.float32)

        # Store items with varying similarity
        items = []
        for i in range(3):
            # Create embedding with varying similarity to query
            embedding = query_embedding + np.random.rand(128).astype(np.float32) * (i + 1) * 0.1
            embedding = embedding / np.linalg.norm(embedding)  # Normalize

            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=f"Content {i}",
                summary=f"Summary {i}",
                context=memory_context,
                importance=0.5,
                tier=MemoryTier.WORKING,
                creator_agent_id="test_agent",
                modifier_agent_id="test_agent",
                embedding=embedding,
            )
            items.append(item)
            await working_memory.store(item)

        # Retrieve with query
        results = await working_memory.retrieve(query_embedding, memory_context, limit=10)

        # Verify results
        assert len(results) == 3
        assert all(r.retrieval_tier == MemoryTier.WORKING for r in results)

        # Verify results are sorted by relevance (descending)
        scores = [r.relevance_score for r in results]
        assert scores == sorted(scores, reverse=True)

    async def test_retrieve_filters_by_context(
        self, working_memory: WorkingMemory, memory_context: MemoryContext
    ) -> None:
        """Test that retrieval filters by agent_id and session_id."""
        query_embedding = np.random.rand(128).astype(np.float32)

        # Store items for test context
        for i in range(2):
            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=f"Content {i}",
                summary=f"Summary {i}",
                context=memory_context,
                importance=0.5,
                tier=MemoryTier.WORKING,
                creator_agent_id="test_agent",
                modifier_agent_id="test_agent",
                embedding=np.random.rand(128).astype(np.float32),
            )
            await working_memory.store(item)

        # Store items for different agent
        other_context = MemoryContext(
            agent_id="other_agent",
            session_id="test_session",
            conversation_id="test_conversation",
        )
        for i in range(2):
            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=f"Other content {i}",
                summary=f"Other summary {i}",
                context=other_context,
                importance=0.5,
                tier=MemoryTier.WORKING,
                creator_agent_id="other_agent",
                modifier_agent_id="other_agent",
                embedding=np.random.rand(128).astype(np.float32),
            )
            await working_memory.store(item)

        # Retrieve with test context
        results = await working_memory.retrieve(query_embedding, memory_context, limit=10)

        # Verify only test context items are returned
        assert len(results) == 2
        assert all(r.item.context.agent_id == "test_agent" for r in results)

    async def test_retrieve_respects_limit(
        self, working_memory: WorkingMemory, memory_context: MemoryContext
    ) -> None:
        """Test that retrieval respects the limit parameter."""
        query_embedding = np.random.rand(128).astype(np.float32)

        # Store 5 items
        for i in range(5):
            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=f"Content {i}",
                summary=f"Summary {i}",
                context=memory_context,
                importance=0.5,
                tier=MemoryTier.WORKING,
                creator_agent_id="test_agent",
                modifier_agent_id="test_agent",
                embedding=np.random.rand(128).astype(np.float32),
            )
            await working_memory.store(item)

        # Retrieve with limit=3
        results = await working_memory.retrieve(query_embedding, memory_context, limit=3)

        # Verify limit is respected
        assert len(results) == 3

    async def test_retrieve_skips_items_without_embeddings(
        self, working_memory: WorkingMemory, memory_context: MemoryContext
    ) -> None:
        """Test that retrieval skips items without embeddings."""
        query_embedding = np.random.rand(128).astype(np.float32)

        # Store item with embedding
        item_with_embedding = MemoryItem(
            id=str(uuid.uuid4()),
            content="Content with embedding",
            summary="Summary",
            context=memory_context,
            importance=0.5,
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(128).astype(np.float32),
        )
        await working_memory.store(item_with_embedding)

        # Store item without embedding
        item_without_embedding = MemoryItem(
            id=str(uuid.uuid4()),
            content="Content without embedding",
            summary="Summary",
            context=memory_context,
            importance=0.5,
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=None,
        )
        await working_memory.store(item_without_embedding)

        # Retrieve
        results = await working_memory.retrieve(query_embedding, memory_context, limit=10)

        # Verify only item with embedding is returned
        assert len(results) == 1
        assert results[0].item.id == item_with_embedding.id

    async def test_retrieve_updates_access_statistics(
        self, working_memory: WorkingMemory, memory_context: MemoryContext
    ) -> None:
        """Test that retrieval updates access statistics."""
        query_embedding = np.random.rand(128).astype(np.float32)

        # Store item
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content="Content",
            summary="Summary",
            context=memory_context,
            importance=0.5,
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(128).astype(np.float32),
        )
        await working_memory.store(item)

        initial_access_count = item.access_count

        # Retrieve
        await working_memory.retrieve(query_embedding, memory_context, limit=10)

        # Verify access count increased
        assert item.access_count == initial_access_count + 1


@pytest.mark.asyncio
class TestWorkingMemoryGetAll:
    """Test get_all_items operations."""

    async def test_get_all_items_no_filter(
        self, working_memory: WorkingMemory, memory_context: MemoryContext
    ) -> None:
        """Test getting all items without filtering."""
        # Store items
        for i in range(3):
            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=f"Content {i}",
                summary=f"Summary {i}",
                context=memory_context,
                importance=0.5,
                tier=MemoryTier.WORKING,
                creator_agent_id="test_agent",
                modifier_agent_id="test_agent",
            )
            await working_memory.store(item)

        # Get all items
        items = await working_memory.get_all_items()

        # Verify all items returned
        assert len(items) == 3

    async def test_get_all_items_with_filter(
        self, working_memory: WorkingMemory, memory_context: MemoryContext
    ) -> None:
        """Test getting all items with context filtering."""
        # Store items for test context
        for i in range(2):
            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=f"Content {i}",
                summary=f"Summary {i}",
                context=memory_context,
                importance=0.5,
                tier=MemoryTier.WORKING,
                creator_agent_id="test_agent",
                modifier_agent_id="test_agent",
            )
            await working_memory.store(item)

        # Store items for different context
        other_context = MemoryContext(
            agent_id="other_agent",
            session_id="other_session",
            conversation_id="other_conversation",
        )
        for i in range(2):
            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=f"Other content {i}",
                summary=f"Other summary {i}",
                context=other_context,
                importance=0.5,
                tier=MemoryTier.WORKING,
                creator_agent_id="other_agent",
                modifier_agent_id="other_agent",
            )
            await working_memory.store(item)

        # Get items with filter
        items = await working_memory.get_all_items(context=memory_context)

        # Verify only test context items returned
        assert len(items) == 2
        assert all(item.context.agent_id == "test_agent" for item in items)


@pytest.mark.asyncio
class TestWorkingMemoryStats:
    """Test statistics operations."""

    async def test_get_stats_empty(self, working_memory: WorkingMemory) -> None:
        """Test statistics for empty memory."""
        stats = working_memory.get_stats()

        assert stats["capacity"] == 5
        assert stats["size"] == 0
        assert stats["utilization"] == 0.0

    async def test_get_stats_partial(
        self, working_memory: WorkingMemory, memory_context: MemoryContext
    ) -> None:
        """Test statistics with partial capacity."""
        # Store 3 items (capacity is 5)
        for i in range(3):
            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=f"Content {i}",
                summary=f"Summary {i}",
                context=memory_context,
                importance=0.5,
                tier=MemoryTier.WORKING,
                creator_agent_id="test_agent",
                modifier_agent_id="test_agent",
            )
            await working_memory.store(item)

        stats = working_memory.get_stats()

        assert stats["capacity"] == 5
        assert stats["size"] == 3
        assert stats["utilization"] == 0.6

    async def test_get_stats_full(
        self, working_memory: WorkingMemory, memory_context: MemoryContext
    ) -> None:
        """Test statistics at full capacity."""
        # Store 5 items (capacity is 5)
        for i in range(5):
            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=f"Content {i}",
                summary=f"Summary {i}",
                context=memory_context,
                importance=0.5,
                tier=MemoryTier.WORKING,
                creator_agent_id="test_agent",
                modifier_agent_id="test_agent",
            )
            await working_memory.store(item)

        stats = working_memory.get_stats()

        assert stats["capacity"] == 5
        assert stats["size"] == 5
        assert stats["utilization"] == 1.0
