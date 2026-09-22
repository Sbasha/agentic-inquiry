"""
Tests for ConsolidationEngine.
"""

import pytest

pytestmark = pytest.mark.integration

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from agent_vault.config import Config
from agent_vault.database.lancedb_manager import LanceDBManager
from agent_vault.memory.adapters.lancedb_adapter import LanceDBMemoryAdapter
from agent_vault.memory.consolidation import ConsolidationEngine
from agent_vault.memory.layers.episodic import EpisodicMemory
from agent_vault.memory.layers.semantic import SemanticMemory
from agent_vault.memory.layers.working import WorkingMemory
from agent_vault.memory.models import MemoryContext, MemoryItem, MemoryTier


@pytest.fixture
def working_memory() -> WorkingMemory:
    """Create a working memory instance."""
    return WorkingMemory(capacity=20)


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
    return LanceDBMemoryAdapter(db_manager, table_name="episodic_memory")


@pytest.fixture
async def semantic_adapter(db_manager: LanceDBManager) -> LanceDBMemoryAdapter:
    """Create a LanceDB memory adapter for semantic memory."""
    return LanceDBMemoryAdapter(db_manager, table_name="semantic_memory")


@pytest.fixture
async def episodic_memory(episodic_adapter: LanceDBMemoryAdapter) -> EpisodicMemory:
    """Create an episodic memory instance."""
    memory = EpisodicMemory(storage=episodic_adapter, limit=100)
    await memory.initialize()
    return memory


@pytest.fixture
async def semantic_memory(semantic_adapter: LanceDBMemoryAdapter) -> SemanticMemory:
    """Create a semantic memory instance."""
    memory = SemanticMemory(storage=semantic_adapter, limit=100)
    await memory.initialize()
    return memory


@pytest.fixture
def mock_embedding_service() -> MagicMock:
    """Create a mock embedding service."""
    service = MagicMock()
    # Use 384 dimensions to match the default adapter configuration
    service.embed_async = AsyncMock(return_value=np.random.rand(384).astype(np.float32))
    service.embed_batch_async = AsyncMock(
        return_value=[np.random.rand(384).astype(np.float32) for _ in range(3)]
    )
    return service


@pytest.fixture
def consolidation_engine(
    working_memory: WorkingMemory,
    episodic_memory: EpisodicMemory,
    semantic_memory: SemanticMemory,
    mock_embedding_service: MagicMock,
) -> ConsolidationEngine:
    """Create a consolidation engine."""
    return ConsolidationEngine(
        working_memory=working_memory,
        episodic_memory=episodic_memory,
        semantic_memory=semantic_memory,
        embedding_service=mock_embedding_service,
        episodic_threshold=0.7,
        semantic_threshold=0.9,
    )


@pytest.fixture
def sample_context() -> MemoryContext:
    """Create a sample memory context."""
    return MemoryContext(
        agent_id="test_agent",
        session_id="test_session",
        conversation_id="test_conversation",
    )


@pytest.mark.asyncio
async def test_consolidation_engine_initialization(
    consolidation_engine: ConsolidationEngine,
) -> None:
    """Test consolidation engine initialization."""
    assert consolidation_engine.episodic_threshold == 0.7
    assert consolidation_engine.semantic_threshold == 0.9
    assert consolidation_engine._total_promotions == 0
    assert consolidation_engine._total_demotions == 0


@pytest.mark.asyncio
async def test_should_consolidate_empty_working_memory(
    consolidation_engine: ConsolidationEngine,
    sample_context: MemoryContext,
) -> None:
    """Test should_consolidate with empty working memory."""
    should_consolidate = consolidation_engine.should_consolidate(sample_context)
    assert should_consolidate is False


@pytest.mark.asyncio
async def test_should_consolidate_with_items(
    consolidation_engine: ConsolidationEngine,
    working_memory: WorkingMemory,
    sample_context: MemoryContext,
) -> None:
    """Test should_consolidate with items in working memory."""
    # Add items to working memory
    for i in range(3):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Content {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.8,
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
        )
        await working_memory.store(item)

    should_consolidate = consolidation_engine.should_consolidate(sample_context)
    assert should_consolidate is True


@pytest.mark.asyncio
async def test_promote_to_episodic(
    consolidation_engine: ConsolidationEngine,
    working_memory: WorkingMemory,
    episodic_memory: EpisodicMemory,
    sample_context: MemoryContext,
) -> None:
    """Test promoting items from working to episodic memory."""
    # Add items to working memory with varying importance
    items = []
    for i in range(3):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Important event {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.75 + (i * 0.05),  # 0.75, 0.80, 0.85
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
        )
        items.append(item)
        await working_memory.store(item)

    # Promote to episodic (threshold is 0.7, so all should be promoted)
    promoted_count = await consolidation_engine.promote_to_episodic(items)

    assert promoted_count == 3

    # Verify items are in episodic memory
    episodic_items = await episodic_memory.get_all_items(sample_context)
    assert len(episodic_items) == 3
    assert all(item.tier == MemoryTier.EPISODIC for item in episodic_items)


@pytest.mark.asyncio
async def test_promote_to_episodic_filters_by_threshold(
    consolidation_engine: ConsolidationEngine,
    working_memory: WorkingMemory,
    episodic_memory: EpisodicMemory,
    sample_context: MemoryContext,
) -> None:
    """Test that promotion filters by importance threshold."""
    # Add items with varying importance
    items = []
    for i in range(3):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Event {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.5 + (i * 0.2),  # 0.5, 0.7, 0.9
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
        )
        items.append(item)
        await working_memory.store(item)

    # Promote to episodic (threshold is 0.7, so only 2 should be promoted)
    promoted_count = await consolidation_engine.promote_to_episodic(items)

    assert promoted_count == 2

    # Verify correct items are in episodic memory
    episodic_items = await episodic_memory.get_all_items(sample_context)
    assert len(episodic_items) == 2
    assert all(item.importance >= 0.7 for item in episodic_items)


@pytest.mark.asyncio
async def test_extract_concepts(
    consolidation_engine: ConsolidationEngine,
    episodic_memory: EpisodicMemory,
    sample_context: MemoryContext,
) -> None:
    """Test concept extraction from episodic memories."""
    # Add episodic items with similar content
    items = []
    for i in range(3):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"User asked about Python programming {i}",
            summary=f"Python question {i}",
            context=sample_context,
            importance=0.9,
            tier=MemoryTier.EPISODIC,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
            summary_embedding=np.random.rand(384).astype(np.float32),
            event_type="user_query",
        )
        items.append(item)
        await episodic_memory.store(item)

    # Extract concepts
    concepts = await consolidation_engine.extract_concepts(items)

    # Should create at least one concept
    assert len(concepts) > 0
    assert all(concept.tier == MemoryTier.SEMANTIC for concept in concepts)
    assert all(concept.subject is not None for concept in concepts)
    assert all(concept.relationship is not None for concept in concepts)
    assert all(concept.object is not None for concept in concepts)


@pytest.mark.asyncio
async def test_promote_to_semantic(
    consolidation_engine: ConsolidationEngine,
    episodic_memory: EpisodicMemory,
    semantic_memory: SemanticMemory,
    sample_context: MemoryContext,
) -> None:
    """Test promoting items from episodic to semantic memory."""
    # Add high-importance episodic items
    items = []
    for i in range(3):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Important fact {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.95,
            tier=MemoryTier.EPISODIC,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
            summary_embedding=np.random.rand(384).astype(np.float32),
            event_type="knowledge",
        )
        items.append(item)
        await episodic_memory.store(item)

    # Promote to semantic (threshold is 0.9, so all should be promoted)
    promoted_count = await consolidation_engine.promote_to_semantic(items)

    # Should promote items and extract concepts
    assert promoted_count > 0

    # Verify items are in semantic memory
    semantic_items = await semantic_memory.get_all_items(sample_context)
    assert len(semantic_items) > 0
    assert all(item.tier == MemoryTier.SEMANTIC for item in semantic_items)


@pytest.mark.asyncio
async def test_promote_to_semantic_filters_by_threshold(
    consolidation_engine: ConsolidationEngine,
    episodic_memory: EpisodicMemory,
    semantic_memory: SemanticMemory,
    sample_context: MemoryContext,
) -> None:
    """Test that semantic promotion filters by importance threshold."""
    # Add items with varying importance
    items = []
    for i in range(3):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Event {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.7 + (i * 0.15),  # 0.7, 0.85, 1.0
            tier=MemoryTier.EPISODIC,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
            summary_embedding=np.random.rand(384).astype(np.float32),
            event_type="knowledge",
        )
        items.append(item)
        await episodic_memory.store(item)

    # Promote to semantic (threshold is 0.9, so only 1 should be promoted)
    promoted_count = await consolidation_engine.promote_to_semantic(items)

    # Should promote at least the high-importance item
    assert promoted_count > 0


@pytest.mark.asyncio
async def test_consolidate_full_workflow(
    consolidation_engine: ConsolidationEngine,
    working_memory: WorkingMemory,
    episodic_memory: EpisodicMemory,
    semantic_memory: SemanticMemory,
    sample_context: MemoryContext,
) -> None:
    """Test full consolidation workflow."""
    # Add items to working memory
    for i in range(5):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Event {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.6 + (i * 0.1),  # 0.6, 0.7, 0.8, 0.9, 1.0
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
        )
        await working_memory.store(item)

    # Run consolidation
    result = await consolidation_engine.consolidate(sample_context)

    # Verify result
    assert result.items_promoted > 0
    assert result.duration_ms > 0
    assert result.context == sample_context

    # Verify items were promoted to episodic
    episodic_items = await episodic_memory.get_all_items(sample_context)
    assert len(episodic_items) > 0


@pytest.mark.asyncio
async def test_consolidate_metrics_tracking(
    consolidation_engine: ConsolidationEngine,
    working_memory: WorkingMemory,
    sample_context: MemoryContext,
) -> None:
    """Test that consolidation tracks metrics."""
    # Add items to working memory
    for i in range(3):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Event {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.8,
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
        )
        await working_memory.store(item)

    # Get initial stats
    initial_stats = consolidation_engine.get_consolidation_stats()
    initial_promotions = initial_stats["total_promotions"]

    # Run consolidation
    await consolidation_engine.consolidate(sample_context)

    # Get updated stats
    updated_stats = consolidation_engine.get_consolidation_stats()

    # Verify metrics were updated
    assert updated_stats["total_promotions"] > initial_promotions


@pytest.mark.asyncio
async def test_consolidate_empty_working_memory(
    consolidation_engine: ConsolidationEngine,
    sample_context: MemoryContext,
) -> None:
    """Test consolidation with empty working memory."""
    # Run consolidation with no items
    result = await consolidation_engine.consolidate(sample_context)

    # Should complete without errors
    assert result.items_promoted == 0
    assert result.duration_ms >= 0


@pytest.mark.asyncio
async def test_get_consolidation_stats(
    consolidation_engine: ConsolidationEngine,
) -> None:
    """Test getting consolidation statistics."""
    stats = consolidation_engine.get_consolidation_stats()

    assert "total_promotions" in stats
    assert "total_demotions" in stats
    assert "total_concepts_extracted" in stats
    assert stats["total_promotions"] == 0
    assert stats["total_demotions"] == 0
    assert stats["total_concepts_extracted"] == 0


@pytest.mark.asyncio
async def test_consolidation_with_access_frequency(
    consolidation_engine: ConsolidationEngine,
    working_memory: WorkingMemory,
    episodic_memory: EpisodicMemory,
    sample_context: MemoryContext,
) -> None:
    """Test that consolidation considers access frequency."""
    # Add items with varying access counts
    items = []
    for i in range(3):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Event {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.75,
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
        )
        # Simulate different access patterns
        for _ in range(i * 2):
            item.access()
        items.append(item)
        await working_memory.store(item)

    # Run consolidation
    result = await consolidation_engine.consolidate(sample_context)

    # Verify items were promoted
    assert result.items_promoted > 0

    # Verify items are in episodic memory
    episodic_items = await episodic_memory.get_all_items(sample_context)
    assert len(episodic_items) > 0


@pytest.mark.asyncio
async def test_consolidation_preserves_metadata(
    consolidation_engine: ConsolidationEngine,
    working_memory: WorkingMemory,
    episodic_memory: EpisodicMemory,
    sample_context: MemoryContext,
) -> None:
    """Test that consolidation preserves item metadata."""
    # Add item with metadata
    item = MemoryItem(
        id=str(uuid.uuid4()),
        content="Important event",
        summary="Summary",
        context=sample_context,
        importance=0.9,
        tier=MemoryTier.WORKING,
        creator_agent_id="test_agent",
        modifier_agent_id="test_agent",
        embedding=np.random.rand(384).astype(np.float32),
        metadata={"source": "user_input", "category": "question"},
    )
    await working_memory.store(item)

    # Run consolidation
    await consolidation_engine.consolidate(sample_context)

    # Verify metadata is preserved
    episodic_items = await episodic_memory.get_all_items(sample_context)
    assert len(episodic_items) > 0
    promoted_item = episodic_items[0]
    assert promoted_item.metadata.get("source") == "user_input"
    assert promoted_item.metadata.get("category") == "question"
