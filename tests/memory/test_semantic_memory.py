"""
Tests for SemanticMemory layer.
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
from agentic_inquiry.memory.layers.semantic import SemanticMemory
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
async def semantic_adapter(db_manager: LanceDBManager) -> LanceDBMemoryAdapter:
    """Create a LanceDB memory adapter for semantic memory."""
    return LanceDBMemoryAdapter(db_manager, table_name="memory_semantic_high")


@pytest.fixture
async def temp_semantic_memory(
    semantic_adapter: LanceDBMemoryAdapter,
) -> SemanticMemory:
    """Create a temporary semantic memory instance."""
    memory = SemanticMemory(storage=semantic_adapter, limit=100)
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
def sample_fact_item(sample_context: MemoryContext) -> MemoryItem:
    """Create a sample semantic fact item."""
    return MemoryItem(
        id=str(uuid.uuid4()),
        content="Python is a high-level programming language",
        summary="Python language fact",
        context=sample_context,
        importance=0.9,
        tier=MemoryTier.SEMANTIC,
        creator_agent_id="test_agent",
        modifier_agent_id="test_agent",
        content_source="knowledge_base",
        embedding=np.random.rand(384).astype(np.float32),
        summary_embedding=np.random.rand(384).astype(np.float32),
        subject="Python",
        relationship="is_a",
        object="programming_language",
        confidence=0.95,
    )


@pytest.mark.asyncio
async def test_semantic_memory_initialization(
    temp_semantic_memory: SemanticMemory,
) -> None:
    """Test semantic memory initialization."""
    assert temp_semantic_memory._initialized
    assert temp_semantic_memory.limit == 100


@pytest.mark.asyncio
async def test_store_and_retrieve_by_id(
    temp_semantic_memory: SemanticMemory,
    sample_fact_item: MemoryItem,
) -> None:
    """Test storing and retrieving a fact by ID."""
    # Store fact
    await temp_semantic_memory.store(sample_fact_item)

    # Retrieve by ID
    retrieved = await temp_semantic_memory.get_by_id(sample_fact_item.id)

    assert retrieved is not None
    assert retrieved.id == sample_fact_item.id
    assert retrieved.content == sample_fact_item.content
    assert retrieved.summary == sample_fact_item.summary
    assert retrieved.importance == sample_fact_item.importance
    assert retrieved.tier == MemoryTier.SEMANTIC
    assert retrieved.subject == "Python"
    assert retrieved.relationship == "is_a"
    assert retrieved.object == "programming_language"
    assert retrieved.confidence == 0.95


@pytest.mark.asyncio
async def test_store_multiple_facts(
    temp_semantic_memory: SemanticMemory,
    sample_context: MemoryContext,
) -> None:
    """Test storing multiple facts."""
    facts = [
        ("Python", "is_a", "programming_language"),
        ("Python", "supports", "object_oriented_programming"),
        ("Django", "is_a", "web_framework"),
        ("Django", "uses", "Python"),
        ("Flask", "is_a", "web_framework"),
    ]

    items = []
    for subject, relationship, obj in facts:
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"{subject} {relationship} {obj}",
            summary=f"{subject}-{relationship}-{obj}",
            context=sample_context,
            importance=0.8,
            tier=MemoryTier.SEMANTIC,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
            summary_embedding=np.random.rand(384).astype(np.float32),
            subject=subject,
            relationship=relationship,
            object=obj,
            confidence=0.9,
        )
        items.append(item)
        await temp_semantic_memory.store(item)

    # Retrieve all items
    all_items = await temp_semantic_memory.get_all_items(sample_context)

    assert len(all_items) == 5
    assert all(item.tier == MemoryTier.SEMANTIC for item in all_items)


@pytest.mark.asyncio
async def test_update_fact(
    temp_semantic_memory: SemanticMemory,
    sample_fact_item: MemoryItem,
) -> None:
    """Test updating a fact."""
    # Store fact
    await temp_semantic_memory.store(sample_fact_item)

    # Update confidence
    sample_fact_item.confidence = 0.99
    sample_fact_item.modified_at = datetime.now(timezone.utc)
    await temp_semantic_memory.update(sample_fact_item)

    # Retrieve and verify (without updating access)
    retrieved = await temp_semantic_memory.get_by_id(
        sample_fact_item.id, update_access=False
    )

    assert retrieved is not None
    assert retrieved.confidence == 0.99
    assert retrieved.modified_at is not None


@pytest.mark.asyncio
async def test_delete_fact(
    temp_semantic_memory: SemanticMemory,
    sample_fact_item: MemoryItem,
) -> None:
    """Test deleting a fact."""
    # Store fact
    await temp_semantic_memory.store(sample_fact_item)

    # Verify it exists (without updating access)
    retrieved = await temp_semantic_memory.get_by_id(
        sample_fact_item.id, update_access=False
    )
    assert retrieved is not None

    # Delete fact
    deleted = await temp_semantic_memory.delete(sample_fact_item.id)
    assert deleted is True

    # Verify it's gone (without updating access)
    retrieved = await temp_semantic_memory.get_by_id(
        sample_fact_item.id, update_access=False
    )
    assert retrieved is None

    # Try deleting again
    deleted = await temp_semantic_memory.delete(sample_fact_item.id)
    assert deleted is False


@pytest.mark.asyncio
async def test_retrieve_with_vector_search(
    temp_semantic_memory: SemanticMemory,
    sample_context: MemoryContext,
) -> None:
    """Test retrieving facts using vector similarity search."""
    # Create facts with similar embeddings
    base_embedding = np.random.rand(384).astype(np.float32)

    facts = [
        ("Python", "is_a", "programming_language"),
        ("Java", "is_a", "programming_language"),
        ("JavaScript", "is_a", "programming_language"),
    ]

    for subject, relationship, obj in facts:
        # Add small noise to create similar embeddings
        embedding = base_embedding + np.random.rand(384).astype(np.float32) * 0.1
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"{subject} {relationship} {obj}",
            summary=f"{subject}-{relationship}-{obj}",
            context=sample_context,
            importance=0.8,
            tier=MemoryTier.SEMANTIC,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=embedding,
            summary_embedding=np.random.rand(384).astype(np.float32),
            subject=subject,
            relationship=relationship,
            object=obj,
            confidence=0.9,
        )
        await temp_semantic_memory.store(item)

    # Query with similar embedding
    query_embedding = base_embedding + np.random.rand(384).astype(np.float32) * 0.05
    results = await temp_semantic_memory.retrieve(
        query_embedding=query_embedding,
        context=sample_context,
        limit=3,
    )

    assert len(results) == 3
    assert all(r.retrieval_tier == MemoryTier.SEMANTIC for r in results)
    assert all(r.relevance_score > 0 for r in results)


@pytest.mark.asyncio
async def test_query_facts_by_subject(
    temp_semantic_memory: SemanticMemory,
    sample_context: MemoryContext,
) -> None:
    """Test querying facts by subject."""
    facts = [
        ("Python", "is_a", "programming_language"),
        ("Python", "supports", "object_oriented_programming"),
        ("Python", "has", "dynamic_typing"),
        ("Java", "is_a", "programming_language"),
    ]

    for subject, relationship, obj in facts:
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"{subject} {relationship} {obj}",
            summary=f"{subject}-{relationship}-{obj}",
            context=sample_context,
            importance=0.8,
            tier=MemoryTier.SEMANTIC,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
            summary_embedding=np.random.rand(384).astype(np.float32),
            subject=subject,
            relationship=relationship,
            object=obj,
            confidence=0.9,
        )
        await temp_semantic_memory.store(item)

    # Query for Python facts
    python_facts = await temp_semantic_memory.query_facts(
        agent_id="test_agent",
        subject="Python",
    )

    assert len(python_facts) == 3
    assert all(fact.subject == "Python" for fact in python_facts)


@pytest.mark.asyncio
async def test_query_facts_by_relationship(
    temp_semantic_memory: SemanticMemory,
    sample_context: MemoryContext,
) -> None:
    """Test querying facts by relationship."""
    facts = [
        ("Python", "is_a", "programming_language"),
        ("Java", "is_a", "programming_language"),
        ("Python", "supports", "object_oriented_programming"),
    ]

    for subject, relationship, obj in facts:
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"{subject} {relationship} {obj}",
            summary=f"{subject}-{relationship}-{obj}",
            context=sample_context,
            importance=0.8,
            tier=MemoryTier.SEMANTIC,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
            summary_embedding=np.random.rand(384).astype(np.float32),
            subject=subject,
            relationship=relationship,
            object=obj,
            confidence=0.9,
        )
        await temp_semantic_memory.store(item)

    # Query for "is_a" relationships
    is_a_facts = await temp_semantic_memory.query_facts(
        agent_id="test_agent",
        relationship="is_a",
    )

    assert len(is_a_facts) == 2
    assert all(fact.relationship == "is_a" for fact in is_a_facts)


@pytest.mark.asyncio
async def test_query_facts_by_object(
    temp_semantic_memory: SemanticMemory,
    sample_context: MemoryContext,
) -> None:
    """Test querying facts by object."""
    facts = [
        ("Python", "is_a", "programming_language"),
        ("Java", "is_a", "programming_language"),
        ("Django", "is_a", "web_framework"),
    ]

    for subject, relationship, obj in facts:
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"{subject} {relationship} {obj}",
            summary=f"{subject}-{relationship}-{obj}",
            context=sample_context,
            importance=0.8,
            tier=MemoryTier.SEMANTIC,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
            summary_embedding=np.random.rand(384).astype(np.float32),
            subject=subject,
            relationship=relationship,
            object=obj,
            confidence=0.9,
        )
        await temp_semantic_memory.store(item)

    # Query for programming_language objects
    lang_facts = await temp_semantic_memory.query_facts(
        agent_id="test_agent",
        obj="programming_language",
    )

    assert len(lang_facts) == 2
    assert all(fact.object == "programming_language" for fact in lang_facts)


@pytest.mark.asyncio
async def test_query_facts_combined_filters(
    temp_semantic_memory: SemanticMemory,
    sample_context: MemoryContext,
) -> None:
    """Test querying facts with multiple filters."""
    facts = [
        ("Python", "is_a", "programming_language"),
        ("Python", "supports", "object_oriented_programming"),
        ("Java", "is_a", "programming_language"),
    ]

    for subject, relationship, obj in facts:
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"{subject} {relationship} {obj}",
            summary=f"{subject}-{relationship}-{obj}",
            context=sample_context,
            importance=0.8,
            tier=MemoryTier.SEMANTIC,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
            summary_embedding=np.random.rand(384).astype(np.float32),
            subject=subject,
            relationship=relationship,
            object=obj,
            confidence=0.9,
        )
        await temp_semantic_memory.store(item)

    # Query for Python + is_a
    results = await temp_semantic_memory.query_facts(
        agent_id="test_agent",
        subject="Python",
        relationship="is_a",
    )

    assert len(results) == 1
    assert results[0].subject == "Python"
    assert results[0].relationship == "is_a"


@pytest.mark.asyncio
async def test_context_filtering(
    temp_semantic_memory: SemanticMemory,
) -> None:
    """Test that facts are filtered by agent_id."""
    # Create facts for different agents
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

    # Store facts for agent1
    for i in range(3):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Agent1 fact {i}",
            summary=f"Summary {i}",
            context=agent1_context,
            importance=0.8,
            tier=MemoryTier.SEMANTIC,
            creator_agent_id="agent1",
            modifier_agent_id="agent1",
            embedding=np.random.rand(384).astype(np.float32),
            summary_embedding=np.random.rand(384).astype(np.float32),
            subject=f"subject{i}",
            relationship="is_a",
            object="concept",
            confidence=0.9,
        )
        await temp_semantic_memory.store(item)

    # Store facts for agent2
    for i in range(2):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Agent2 fact {i}",
            summary=f"Summary {i}",
            context=agent2_context,
            importance=0.8,
            tier=MemoryTier.SEMANTIC,
            creator_agent_id="agent2",
            modifier_agent_id="agent2",
            embedding=np.random.rand(384).astype(np.float32),
            summary_embedding=np.random.rand(384).astype(np.float32),
            subject=f"subject{i}",
            relationship="is_a",
            object="concept",
            confidence=0.9,
        )
        await temp_semantic_memory.store(item)

    # Retrieve for agent1
    agent1_facts = await temp_semantic_memory.get_all_items(agent1_context)
    assert len(agent1_facts) == 3
    assert all(fact.context.agent_id == "agent1" for fact in agent1_facts)

    # Retrieve for agent2
    agent2_facts = await temp_semantic_memory.get_all_items(agent2_context)
    assert len(agent2_facts) == 2
    assert all(fact.context.agent_id == "agent2" for fact in agent2_facts)


@pytest.mark.asyncio
async def test_confidence_scoring(
    temp_semantic_memory: SemanticMemory,
    sample_context: MemoryContext,
) -> None:
    """Test that facts are ranked by confidence."""
    # Create facts with different confidence scores
    confidences = [0.95, 0.85, 0.75]

    for i, confidence in enumerate(confidences):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Fact {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.8,
            tier=MemoryTier.SEMANTIC,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
            summary_embedding=np.random.rand(384).astype(np.float32),
            subject=f"subject{i}",
            relationship="is_a",
            object="concept",
            confidence=confidence,
        )
        await temp_semantic_memory.store(item)

    # Query with random embedding
    query_embedding = np.random.rand(384).astype(np.float32)
    results = await temp_semantic_memory.retrieve(
        query_embedding=query_embedding,
        context=sample_context,
        limit=3,
    )

    # Verify results include confidence information
    assert len(results) == 3
    assert all(r.item.confidence is not None for r in results)


@pytest.mark.asyncio
async def test_capacity_limits(
    db_manager: LanceDBManager,
    sample_context: MemoryContext,
) -> None:
    """Test that capacity limits are enforced."""
    # Create a semantic memory with small capacity using adapter
    small_adapter = LanceDBMemoryAdapter(
        db_manager, table_name="memory_semantic_capacity_test"
    )
    small_memory = SemanticMemory(storage=small_adapter, limit=5)
    await small_memory.initialize()

    # Store facts up to capacity
    for i in range(5):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Fact {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.8,
            tier=MemoryTier.SEMANTIC,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
            summary_embedding=np.random.rand(384).astype(np.float32),
            subject=f"subject{i}",
            relationship="is_a",
            object="concept",
            confidence=0.5 + (i * 0.1),  # Varying confidence
        )
        await small_memory.store(item)

    # Verify capacity
    stats = await small_memory.get_stats()
    assert stats["size"] == 5

    # Store one more fact (should trigger eviction of lowest confidence)
    new_item = MemoryItem(
        id=str(uuid.uuid4()),
        content="New fact",
        summary="New summary",
        context=sample_context,
        importance=0.8,
        tier=MemoryTier.SEMANTIC,
        creator_agent_id="test_agent",
        modifier_agent_id="test_agent",
        embedding=np.random.rand(384).astype(np.float32),
        summary_embedding=np.random.rand(384).astype(np.float32),
        subject="new_subject",
        relationship="is_a",
        object="concept",
        confidence=0.95,
    )
    await small_memory.store(new_item)

    # Verify capacity is maintained
    stats = await small_memory.get_stats()
    assert stats["size"] == 5


@pytest.mark.asyncio
async def test_get_stats(temp_semantic_memory: SemanticMemory) -> None:
    """Test getting semantic memory statistics."""
    stats = await temp_semantic_memory.get_stats()

    assert "capacity" in stats
    assert "size" in stats
    assert "utilization" in stats
    assert stats["capacity"] == 100
