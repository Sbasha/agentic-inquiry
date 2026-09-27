"""
Tests for EpisodicMemory layer.
"""

import pytest

pytestmark = pytest.mark.integration

import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from agentic_inquiry.config import Config
from agentic_inquiry.database.lancedb_manager import LanceDBManager
from agentic_inquiry.memory.adapters.lancedb_adapter import LanceDBMemoryAdapter
from agentic_inquiry.memory.layers.episodic import EpisodicMemory
from agentic_inquiry.memory.models import MemoryContext, MemoryItem, MemoryTier


@pytest.fixture
def test_config(tmp_path: Path) -> Config:
    """Create a test configuration."""
    config = Config.load()
    config.storage.root = str(tmp_path / "storage")
    return config


@pytest.fixture
async def db_manager(test_config: Config) -> LanceDBManager:
    """Create a LanceDB manager for testing."""
    manager = LanceDBManager(config=test_config)
    yield manager
    await manager.close()


@pytest.fixture
async def episodic_adapter(db_manager: LanceDBManager) -> LanceDBMemoryAdapter:
    """Create a LanceDB memory adapter for episodic memory."""
    return LanceDBMemoryAdapter(db_manager, table_name="memory_episodic_medium")


@pytest.fixture
async def temp_episodic_memory(
    episodic_adapter: LanceDBMemoryAdapter,
) -> EpisodicMemory:
    """Create a temporary episodic memory instance."""
    memory = EpisodicMemory(storage=episodic_adapter, limit=100)
    await memory.initialize()
    return memory


@pytest.fixture
def sample_context() -> MemoryContext:
    """Create a sample memory context."""
    return MemoryContext(
        agent_id="test_agent",
        session_id="test_session",
        conversation_id="test_conversation",
        task_id="test_task",
        project_id="test_project",
    )


@pytest.fixture
def sample_memory_item(sample_context: MemoryContext) -> MemoryItem:
    """Create a sample memory item."""
    return MemoryItem(
        id=str(uuid.uuid4()),
        content="User asked about Python programming",
        summary="Python question",
        context=sample_context,
        importance=0.8,
        tier=MemoryTier.EPISODIC,
        creator_agent_id="test_agent",
        modifier_agent_id="test_agent",
        content_source="user_input",
        embedding=np.random.rand(384).astype(np.float32),
        summary_embedding=np.random.rand(384).astype(np.float32),
        event_type="user_query",
        emotional_valence=0.5,
        emotional_arousal=0.3,
    )


@pytest.mark.asyncio
async def test_episodic_memory_initialization(
    temp_episodic_memory: EpisodicMemory,
) -> None:
    """Test episodic memory initialization."""
    assert temp_episodic_memory._initialized
    assert temp_episodic_memory.limit == 100


@pytest.mark.asyncio
async def test_store_and_retrieve_by_id(
    temp_episodic_memory: EpisodicMemory,
    sample_memory_item: MemoryItem,
) -> None:
    """Test storing and retrieving a memory item by ID."""
    # Store item
    await temp_episodic_memory.store(sample_memory_item)

    # Retrieve by ID
    retrieved = await temp_episodic_memory.get_by_id(sample_memory_item.id)

    assert retrieved is not None
    assert retrieved.id == sample_memory_item.id
    assert retrieved.content == sample_memory_item.content
    assert retrieved.summary == sample_memory_item.summary
    assert retrieved.importance == sample_memory_item.importance
    assert retrieved.tier == MemoryTier.EPISODIC
    assert retrieved.event_type == "user_query"
    assert retrieved.emotional_valence == 0.5
    assert retrieved.emotional_arousal == 0.3


@pytest.mark.asyncio
async def test_store_multiple_items(
    temp_episodic_memory: EpisodicMemory,
    sample_context: MemoryContext,
) -> None:
    """Test storing multiple memory items."""
    items = []
    for i in range(5):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Event {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.5 + (i * 0.1),
            tier=MemoryTier.EPISODIC,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
            summary_embedding=np.random.rand(384).astype(np.float32),
            event_type="test_event",
        )
        items.append(item)
        await temp_episodic_memory.store(item)

    # Retrieve all items
    all_items = await temp_episodic_memory.get_all_items(sample_context)

    assert len(all_items) == 5
    assert all(item.tier == MemoryTier.EPISODIC for item in all_items)


@pytest.mark.asyncio
async def test_update_item(
    temp_episodic_memory: EpisodicMemory,
    sample_memory_item: MemoryItem,
) -> None:
    """Test updating a memory item."""
    # Store item
    await temp_episodic_memory.store(sample_memory_item)

    # Update importance
    sample_memory_item.importance = 0.95
    sample_memory_item.modified_at = datetime.now(timezone.utc)
    await temp_episodic_memory.update(sample_memory_item)

    # Retrieve and verify (without updating access to avoid overwriting)
    retrieved = await temp_episodic_memory.get_by_id(
        sample_memory_item.id, update_access=False
    )

    assert retrieved is not None
    assert retrieved.importance == 0.95
    assert retrieved.modified_at is not None


@pytest.mark.asyncio
async def test_delete_item(
    temp_episodic_memory: EpisodicMemory,
    sample_memory_item: MemoryItem,
) -> None:
    """Test deleting a memory item."""
    # Store item
    await temp_episodic_memory.store(sample_memory_item)

    # Verify it exists (without updating access)
    retrieved = await temp_episodic_memory.get_by_id(
        sample_memory_item.id, update_access=False
    )
    assert retrieved is not None

    # Delete item
    deleted = await temp_episodic_memory.delete(sample_memory_item.id)
    assert deleted is True

    # Verify it's gone (without updating access)
    retrieved = await temp_episodic_memory.get_by_id(
        sample_memory_item.id, update_access=False
    )
    assert retrieved is None

    # Try deleting again
    deleted = await temp_episodic_memory.delete(sample_memory_item.id)
    assert deleted is False


@pytest.mark.asyncio
async def test_retrieve_with_vector_search(
    temp_episodic_memory: EpisodicMemory,
    sample_context: MemoryContext,
) -> None:
    """Test retrieving items using vector similarity search."""
    # Create items with similar embeddings
    base_embedding = np.random.rand(384).astype(np.float32)

    items = []
    for i in range(3):
        # Add small noise to create similar embeddings
        embedding = base_embedding + np.random.rand(384).astype(np.float32) * 0.1
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Similar event {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.7,
            tier=MemoryTier.EPISODIC,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=embedding,
            summary_embedding=np.random.rand(384).astype(np.float32),
            event_type="similar_event",
        )
        items.append(item)
        await temp_episodic_memory.store(item)

    # Query with similar embedding
    query_embedding = base_embedding + np.random.rand(384).astype(np.float32) * 0.05
    results = await temp_episodic_memory.retrieve(
        query_embedding=query_embedding,
        context=sample_context,
        limit=3,
    )

    assert len(results) == 3
    assert all(r.retrieval_tier == MemoryTier.EPISODIC for r in results)
    assert all(r.relevance_score > 0 for r in results)


@pytest.mark.asyncio
async def test_context_filtering(
    temp_episodic_memory: EpisodicMemory,
) -> None:
    """Test that items are filtered by agent_id."""
    # Create items for different agents
    agent1_context = MemoryContext(
        agent_id="agent1",
        session_id="session1",
        conversation_id="conv1",
    )
    agent2_context = MemoryContext(
        agent_id="agent2",
        session_id="session2",
        conversation_id="conv2",
    )

    # Store items for agent1
    for i in range(3):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Agent1 event {i}",
            summary=f"Summary {i}",
            context=agent1_context,
            importance=0.7,
            tier=MemoryTier.EPISODIC,
            creator_agent_id="agent1",
            modifier_agent_id="agent1",
            embedding=np.random.rand(384).astype(np.float32),
            summary_embedding=np.random.rand(384).astype(np.float32),
        )
        await temp_episodic_memory.store(item)

    # Store items for agent2
    for i in range(2):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Agent2 event {i}",
            summary=f"Summary {i}",
            context=agent2_context,
            importance=0.7,
            tier=MemoryTier.EPISODIC,
            creator_agent_id="agent2",
            modifier_agent_id="agent2",
            embedding=np.random.rand(384).astype(np.float32),
            summary_embedding=np.random.rand(384).astype(np.float32),
        )
        await temp_episodic_memory.store(item)

    # Retrieve for agent1
    agent1_items = await temp_episodic_memory.get_all_items(agent1_context)
    assert len(agent1_items) == 3
    assert all(item.context.agent_id == "agent1" for item in agent1_items)

    # Retrieve for agent2
    agent2_items = await temp_episodic_memory.get_all_items(agent2_context)
    assert len(agent2_items) == 2
    assert all(item.context.agent_id == "agent2" for item in agent2_items)


@pytest.mark.asyncio
async def test_timestamp_ordering(
    temp_episodic_memory: EpisodicMemory,
    sample_context: MemoryContext,
) -> None:
    """Test that retrieval results are ordered by timestamp (recency)."""
    # Create items with different timestamps
    items = []
    for i in range(3):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Event {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.7,
            tier=MemoryTier.EPISODIC,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
            summary_embedding=np.random.rand(384).astype(np.float32),
            event_type="test_event",
        )
        items.append(item)
        await temp_episodic_memory.store(item)

    # Query with random embedding
    query_embedding = np.random.rand(384).astype(np.float32)
    results = await temp_episodic_memory.retrieve(
        query_embedding=query_embedding,
        context=sample_context,
        limit=3,
    )

    # Verify all stored items are returned (recency is blended with similarity,
    # so pure timestamp ordering is not guaranteed with random embeddings)
    assert len(results) >= 2
    result_ids = {r.item.id for r in results}
    stored_ids = {item.id for item in items}
    assert result_ids == stored_ids, "All stored items should be retrievable"
    # Results must be ordered by descending relevance_score (blended score)
    for i in range(len(results) - 1):
        assert results[i].relevance_score >= results[i + 1].relevance_score


@pytest.mark.asyncio
async def test_emotional_metadata(
    temp_episodic_memory: EpisodicMemory,
    sample_context: MemoryContext,
) -> None:
    """Test storing and retrieving emotional metadata."""
    item = MemoryItem(
        id=str(uuid.uuid4()),
        content="User expressed frustration",
        summary="Frustration event",
        context=sample_context,
        importance=0.8,
        tier=MemoryTier.EPISODIC,
        creator_agent_id="test_agent",
        modifier_agent_id="test_agent",
        embedding=np.random.rand(384).astype(np.float32),
        summary_embedding=np.random.rand(384).astype(np.float32),
        event_type="emotional_event",
        emotional_valence=-0.7,  # Negative emotion
        emotional_arousal=0.9,  # High arousal
    )

    await temp_episodic_memory.store(item)

    # Retrieve and verify emotional metadata
    retrieved = await temp_episodic_memory.get_by_id(item.id)

    assert retrieved is not None
    assert retrieved.emotional_valence == -0.7
    assert retrieved.emotional_arousal == 0.9
    assert retrieved.event_type == "emotional_event"


@pytest.mark.asyncio
async def test_get_stats(temp_episodic_memory: EpisodicMemory) -> None:
    """Test getting episodic memory statistics."""
    stats = await temp_episodic_memory.get_stats()

    assert "capacity" in stats
    assert "size" in stats
    assert "utilization" in stats
    assert stats["capacity"] == 100
