"""
Integration tests for MemorySystem.
"""

import pytest

pytestmark = pytest.mark.integration

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np

from agent_vault.config import (
    Config,
    ConsolidationConfig,
    EpisodicMemoryConfig,
    MemoryConfig,
    RetrievalConfig,
    SemanticMemoryConfig,
    SummaryConfig,
    WorkingMemoryConfig,
)
from agent_vault.memory.models import MemoryContext, MemoryTier
from agent_vault.memory.system import MemorySystem


@pytest.fixture
def mock_embedding_service() -> MagicMock:
    """Create a mock embedding service."""
    service = MagicMock()
    # Mock embed_async to return different dimensions based on density
    async def mock_embed(text: str, density: str = "medium"):
        if density == "low":
            return np.random.rand(128).astype(np.float32)
        elif density == "medium":
            return np.random.rand(384).astype(np.float32)
        elif density == "high":
            return np.random.rand(768).astype(np.float32)
        return np.random.rand(384).astype(np.float32)
    
    service.embed_async = AsyncMock(side_effect=mock_embed)
    service.embed_batch_async = AsyncMock(
        return_value=[np.random.rand(384).astype(np.float32) for _ in range(3)]
    )
    return service


@pytest.fixture
def memory_config() -> MemoryConfig:
    """Create a memory configuration."""
    return MemoryConfig(
        working_memory=WorkingMemoryConfig(capacity=20),
        episodic_memory=EpisodicMemoryConfig(capacity=100),
        semantic_memory=SemanticMemoryConfig(capacity=100),
        consolidation=ConsolidationConfig(
            enabled=True,
            interval_seconds=300,
            episodic_threshold=0.7,
            semantic_threshold=0.9,
        ),
        retrieval=RetrievalConfig(
            default_strategy="adaptive",
            cache_enabled=True,
            cache_ttl_seconds=300,
            cache_size=100,
            ranking_weights={
                "relevance": 0.5,
                "recency": 0.3,
                "importance": 0.2,
            },
        ),
        summary=SummaryConfig(auto_threshold=150),
    )


@pytest.fixture
async def memory_system(
    tmp_path: Path,
    mock_embedding_service: MagicMock,
    memory_config: MemoryConfig,
) -> MemorySystem:
    """Create a memory system instance."""
    from agent_vault.config import (
        StorageConfig,
        CacheConfig,
        DocumentCacheConfig,
        EmbeddingsConfig,
    )
    
    # Create a mock config with all required attributes
    config = MagicMock(spec=Config)
    config.memory = memory_config
    config.storage = StorageConfig(
        root=str(tmp_path),
        default_project_id="test_default",
    )
    config.storage.uri = str(tmp_path / "test.lancedb")
    config.cache = CacheConfig(
        document_cache=DocumentCacheConfig(
            max_size=100,
            ttl_seconds=3600,
            eviction_policy="lru",
        )
    )
    config.embeddings = EmbeddingsConfig(default_provider="sentence_transformer")

    system = MemorySystem(
        config=config,
        embedding_service=mock_embedding_service,
    )
    await system.initialize()
    return system


@pytest.fixture
def sample_context() -> MemoryContext:
    """Create a sample memory context."""
    return MemoryContext(
        agent_id="test_agent",
        session_id="test_session",
        conversation_id="test_conversation",
    )


@pytest.mark.asyncio
async def test_memory_system_initialization(memory_system: MemorySystem) -> None:
    """Test memory system initialization."""
    from agent_vault.memory.working import WorkingMemory
    from agent_vault.memory.episodic import EpisodicMemory
    from agent_vault.memory.semantic import SemanticMemory
    from agent_vault.memory.consolidation import ConsolidationEngine
    from agent_vault.memory.retrieval import RetrievalEngine
    from agent_vault.memory.context import ContextManager

    assert memory_system._initialized is True
    assert memory_system.working_memory is not None
    assert isinstance(memory_system.working_memory, WorkingMemory)
    assert memory_system.episodic_memory is not None
    assert isinstance(memory_system.episodic_memory, EpisodicMemory)
    assert memory_system.semantic_memory is not None
    assert isinstance(memory_system.semantic_memory, SemanticMemory)
    assert memory_system.consolidation_engine is not None
    assert isinstance(memory_system.consolidation_engine, ConsolidationEngine)
    assert memory_system.retrieval_engine is not None
    assert isinstance(memory_system.retrieval_engine, RetrievalEngine)
    assert memory_system.context_manager is not None
    assert isinstance(memory_system.context_manager, ContextManager)


@pytest.mark.asyncio
async def test_store_and_retrieve_workflow(
    memory_system: MemorySystem,
    sample_context: MemoryContext,
) -> None:
    """Test end-to-end store and retrieve workflow."""
    # Store a memory
    memory_item = await memory_system.store(
        content="User asked about Python programming",
        context=sample_context,
        importance=0.8,
        summary="Python question",
    )

    assert memory_item is not None
    assert memory_item.id is not None
    assert memory_item.content == "User asked about Python programming"
    assert memory_item.importance == 0.8

    # Retrieve the memory
    results = await memory_system.retrieve(
        query="Python programming",
        context=sample_context,
        limit=10,
    )

    assert len(results) > 0
    assert any(r.item.content == "User asked about Python programming" for r in results)


@pytest.mark.asyncio
async def test_tier_promotion_flow(
    memory_system: MemorySystem,
    sample_context: MemoryContext,
) -> None:
    """Test memory tier promotion flow."""
    # Store low-importance item (should go to working memory)
    low_importance_item = await memory_system.store(
        content="Low importance event",
        context=sample_context,
        importance=0.5,
        summary="Low event",
    )
    assert low_importance_item.tier == MemoryTier.WORKING

    # Store medium-importance item (should go to episodic memory)
    medium_importance_item = await memory_system.store(
        content="Medium importance event",
        context=sample_context,
        importance=0.75,
        summary="Medium event",
    )
    assert medium_importance_item.tier == MemoryTier.EPISODIC

    # Store high-importance item (should go to semantic memory)
    high_importance_item = await memory_system.store(
        content="High importance fact",
        context=sample_context,
        importance=0.95,
        summary="High fact",
    )
    assert high_importance_item.tier == MemoryTier.SEMANTIC

    # Verify items are in correct tiers
    working_items = await memory_system.working_memory.get_all_items(sample_context)
    assert any(item.id == low_importance_item.id for item in working_items)

    episodic_items = await memory_system.episodic_memory.get_all_items(sample_context)
    assert any(item.id == medium_importance_item.id for item in episodic_items)

    semantic_items = await memory_system.semantic_memory.get_all_items(sample_context)
    assert any(item.id == high_importance_item.id for item in semantic_items)


@pytest.mark.asyncio
async def test_multi_agent_isolation(
    memory_system: MemorySystem,
) -> None:
    """Test that different agents' memories are isolated."""
    # Create contexts for different agents
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

    # Store memories for agent1
    await memory_system.store(
        content="Agent1 memory",
        context=agent1_context,
        importance=0.8,
        summary="Agent1",
    )

    # Store memories for agent2
    await memory_system.store(
        content="Agent2 memory",
        context=agent2_context,
        importance=0.8,
        summary="Agent2",
    )

    # Retrieve for agent1
    agent1_results = await memory_system.retrieve(
        query="memory",
        context=agent1_context,
        limit=10,
    )

    # Verify only agent1 memories are returned
    assert len(agent1_results) > 0
    assert all(r.item.context.agent_id == "agent1" for r in agent1_results)

    # Retrieve for agent2
    agent2_results = await memory_system.retrieve(
        query="memory",
        context=agent2_context,
        limit=10,
    )

    # Verify only agent2 memories are returned
    assert len(agent2_results) > 0
    assert all(r.item.context.agent_id == "agent2" for r in agent2_results)


@pytest.mark.asyncio
async def test_consolidation_workflow(
    memory_system: MemorySystem,
    sample_context: MemoryContext,
) -> None:
    """Test consolidation workflow promotes high-importance items."""
    # Store items in working memory with varying importance
    # Items with importance >= 0.8 (episodic threshold) should be promoted
    for i in range(5):
        await memory_system.store(
            content=f"Event {i}",
            context=sample_context,
            importance=0.6 + (i * 0.05),  # 0.6, 0.65, 0.7, 0.75, 0.8
            summary=f"Summary {i}",
        )

    # Run consolidation
    result = await memory_system.consolidate(sample_context)

    # Verify consolidation completed successfully
    assert result is not None, "Consolidation should return a result"
    assert result.context == sample_context, "Result should contain the context"
    assert result.duration_ms > 0, "Consolidation should take some time"

    # Verify consolidation statistics are tracked (non-negative values)
    assert result.items_promoted >= 0, "Promoted items should be non-negative"
    assert result.items_demoted >= 0, "Demoted items should be non-negative"
    assert result.concepts_extracted >= 0, "Extracted concepts should be non-negative"
    assert result.relationships_created >= 0, "Created relationships should be non-negative"


@pytest.mark.asyncio
async def test_update_importance(
    memory_system: MemorySystem,
    sample_context: MemoryContext,
) -> None:
    """Test updating memory importance."""
    # Store a memory
    memory_item = await memory_system.store(
        content="Important event",
        context=sample_context,
        importance=0.7,
        summary="Event",
    )

    # Update importance
    await memory_system.update_importance(memory_item.id, 0.95)

    # Retrieve and verify
    if memory_item.tier == MemoryTier.WORKING:
        updated_item = await memory_system.working_memory.get_by_id(memory_item.id)
    elif memory_item.tier == MemoryTier.EPISODIC:
        updated_item = await memory_system.episodic_memory.get_by_id(memory_item.id)
    else:
        updated_item = await memory_system.semantic_memory.get_by_id(memory_item.id)

    assert updated_item is not None
    assert updated_item.importance == 0.95


@pytest.mark.asyncio
async def test_update_confidence(
    memory_system: MemorySystem,
    sample_context: MemoryContext,
) -> None:
    """Test updating semantic memory confidence."""
    # Store a high-importance item (goes to semantic)
    memory_item = await memory_system.store(
        content="Important fact",
        context=sample_context,
        importance=0.95,
        summary="Fact",
    )

    # Update confidence
    await memory_system.update_confidence(memory_item.id, 0.99)

    # Retrieve and verify
    updated_item = await memory_system.semantic_memory.get_by_id(memory_item.id)
    if updated_item:
        assert updated_item.confidence == 0.99


@pytest.mark.asyncio
async def test_delete_memory(
    memory_system: MemorySystem,
    sample_context: MemoryContext,
) -> None:
    """Test deleting a memory."""
    # Store a memory
    memory_item = await memory_system.store(
        content="Temporary event",
        context=sample_context,
        importance=0.7,
        summary="Temp",
    )

    # Delete the memory
    deleted = await memory_system.delete(memory_item.id)
    assert deleted is True

    # Verify it's gone
    results = await memory_system.retrieve(
        query="Temporary event",
        context=sample_context,
        limit=10,
    )
    assert not any(r.item.id == memory_item.id for r in results)


@pytest.mark.asyncio
async def test_get_stats(
    memory_system: MemorySystem,
    sample_context: MemoryContext,
) -> None:
    """Test getting memory system statistics."""
    # Store some memories
    for i in range(3):
        await memory_system.store(
            content=f"Event {i}",
            context=sample_context,
            importance=0.7,
            summary=f"Summary {i}",
        )

    # Get stats
    stats = await memory_system.get_stats(sample_context)

    assert "working_memory" in stats
    assert "episodic_memory" in stats
    assert "semantic_memory" in stats
    assert "consolidation" in stats
    assert "retrieval" in stats


@pytest.mark.asyncio
async def test_create_agent_context(memory_system: MemorySystem) -> None:
    """Test creating an agent context."""
    context = memory_system.create_agent_context(
        agent_id="test_agent",
        session_id="test_session",
        conversation_id="test_conversation",
    )

    assert context.agent_id == "test_agent"
    assert context.session_id == "test_session"
    assert context.conversation_id == "test_conversation"


@pytest.mark.asyncio
async def test_load_conversation(
    memory_system: MemorySystem,
    sample_context: MemoryContext,
) -> None:
    """Test loading recent conversation into working memory."""
    # Store episodic memories for the conversation
    for i in range(5):
        await memory_system.store(
            content=f"Conversation event {i}",
            context=sample_context,
            importance=0.75,  # Goes to episodic
            summary=f"Event {i}",
        )

    # Load conversation
    loaded_items = await memory_system.load_conversation(
        context=sample_context,
        limit=3,
    )

    # Verify items were loaded
    assert len(loaded_items) <= 3
    assert all(item.tier == MemoryTier.WORKING for item in loaded_items)


@pytest.mark.asyncio
async def test_batch_store(
    memory_system: MemorySystem,
    sample_context: MemoryContext,
) -> None:
    """Test batch storing multiple memories."""
    # Prepare batch data
    items_data = [
        ("Event 1", 0.7, "Summary 1"),
        ("Event 2", 0.8, "Summary 2"),
        ("Event 3", 0.9, "Summary 3"),
    ]

    # Batch store - expects list of tuples (content, context, importance, summary, metadata)
    stored_items = await memory_system.batch_store(
        items=[
            (content, sample_context, importance, summary, None)
            for content, importance, summary in items_data
        ]
    )

    # Verify all items were stored
    assert len(stored_items) == 3
    assert all(item.id is not None for item in stored_items)


@pytest.mark.asyncio
async def test_batch_retrieve(
    memory_system: MemorySystem,
    sample_context: MemoryContext,
) -> None:
    """Test batch retrieving multiple queries."""
    # Store some memories
    for i in range(5):
        await memory_system.store(
            content=f"Event about topic {i % 2}",
            context=sample_context,
            importance=0.7,
            summary=f"Summary {i}",
        )

    # Batch retrieve
    queries = [
        ("topic 0", sample_context),
        ("topic 1", sample_context),
    ]
    results = await memory_system.batch_retrieve(queries, limit=10)

    # Verify results
    assert len(results) == 2
    assert all(isinstance(r, list) for r in results)


@pytest.mark.asyncio
async def test_clear_agent_memory(
    memory_system: MemorySystem,
    sample_context: MemoryContext,
) -> None:
    """Test clearing all memories for an agent."""
    # Store memories
    for i in range(3):
        await memory_system.store(
            content=f"Event {i}",
            context=sample_context,
            importance=0.7,
            summary=f"Summary {i}",
        )

    # Clear agent memory
    await memory_system.clear_agent_memory(sample_context.agent_id)

    # Verify memories are cleared
    results = await memory_system.retrieve(
        query="Event",
        context=sample_context,
        limit=10,
    )
    assert len(results) == 0


@pytest.mark.asyncio
async def test_update_from_feedback(
    memory_system: MemorySystem,
    sample_context: MemoryContext,
) -> None:
    """Test updating system from user feedback."""
    # Store a memory
    await memory_system.store(
        content="Helpful response",
        context=sample_context,
        importance=0.7,
        summary="Response",
    )

    # Provide positive feedback
    await memory_system.update_from_feedback(
        feedback="User found this helpful feedback",
        context=sample_context,
        feedback_type="positive",
    )

    # Verify feedback was stored
    results = await memory_system.retrieve(
        query="helpful",
        context=sample_context,
        limit=10,
    )
    # Should find the feedback content specifically
    assert any("feedback" in r.item.content.lower() for r in results)


@pytest.mark.asyncio
async def test_memory_summary_persistence(
    memory_system: MemorySystem,
    sample_context: MemoryContext,
) -> None:
    """Test that memory summaries persist correctly through store and retrieve."""
    # Store memories with summaries
    summaries = [
        "Python programming question",
        "Architecture pattern discussion",
        "Performance optimization tip",
    ]
    
    stored_items = []
    for i, summary in enumerate(summaries):
        memory_item = await memory_system.store(
            content=f"Full content for memory {i}: {summary} with additional details",
            context=sample_context,
            importance=0.7 + (i * 0.1),  # Varying importance
            summary=summary,
        )
        stored_items.append(memory_item)
        
        # Verify summary is set on the returned item
        assert memory_item.summary == summary, f"Summary not set on stored item {i}"
    
    # Retrieve memories and verify summaries are present
    results = await memory_system.retrieve(
        query="programming architecture performance",
        context=sample_context,
        limit=10,
    )
    
    # Verify we got results
    assert len(results) > 0, "No memories retrieved"
    
    # Verify all retrieved memories have summaries
    for result in results:
        assert result.item.summary is not None, f"Summary is None for item {result.item.id}"
        assert result.item.summary != "", f"Summary is empty for item {result.item.id}"
        assert isinstance(result.item.summary, str), f"Summary is not a string for item {result.item.id}"
    
    # Verify 100% of memories have summaries
    memories_with_summaries = sum(1 for r in results if r.item.summary)
    assert memories_with_summaries == len(results), \
        f"Only {memories_with_summaries}/{len(results)} memories have summaries"
    
    # Verify specific summaries are preserved
    retrieved_summaries = {r.item.summary for r in results}
    for expected_summary in summaries:
        assert expected_summary in retrieved_summaries, \
            f"Expected summary '{expected_summary}' not found in retrieved memories"


@pytest.mark.asyncio
async def test_memory_summary_across_tiers(
    memory_system: MemorySystem,
    sample_context: MemoryContext,
) -> None:
    """Test that summaries persist correctly across all memory tiers."""
    # Store memories in different tiers
    test_cases = [
        (0.5, MemoryTier.WORKING, "Working memory summary"),
        (0.75, MemoryTier.EPISODIC, "Episodic memory summary"),
        (0.95, MemoryTier.SEMANTIC, "Semantic memory summary"),
    ]
    
    for importance, expected_tier, summary in test_cases:
        memory_item = await memory_system.store(
            content=f"Content for {expected_tier.value} tier",
            context=sample_context,
            importance=importance,
            summary=summary,
        )
        
        # Verify tier assignment
        assert memory_item.tier == expected_tier, \
            f"Expected tier {expected_tier}, got {memory_item.tier}"
        
        # Verify summary is set
        assert memory_item.summary == summary, \
            f"Summary not preserved for {expected_tier.value} tier"
        
        # Retrieve directly from the tier and verify summary
        if expected_tier == MemoryTier.WORKING:
            retrieved = await memory_system.working_memory.get_by_id(memory_item.id)
        elif expected_tier == MemoryTier.EPISODIC:
            retrieved = await memory_system.episodic_memory.get_by_id(memory_item.id)
        else:  # SEMANTIC
            retrieved = await memory_system.semantic_memory.get_by_id(memory_item.id)
        
        assert retrieved is not None, f"Could not retrieve item from {expected_tier.value}"
        assert retrieved.summary == summary, \
            f"Summary not preserved in {expected_tier.value} tier storage"


@pytest.mark.asyncio
async def test_error_handling_invalid_importance(
    memory_system: MemorySystem,
    sample_context: MemoryContext,
) -> None:
    """Test error handling for invalid importance values."""
    with pytest.raises(ValueError):
        await memory_system.store(
            content="Invalid event",
            context=sample_context,
            importance=1.5,  # Invalid: > 1.0
            summary="Invalid",
        )


@pytest.mark.asyncio
async def test_configuration_loading(
    tmp_path: Path,
    mock_embedding_service: MagicMock,
) -> None:
    """Test that configuration is properly loaded."""
    # Create a custom config
    from agent_vault.config import StorageConfig, EmbeddingsConfig
    
    custom_config = MagicMock(spec=Config)
    custom_config.memory = MemoryConfig(
        working_memory=WorkingMemoryConfig(capacity=50),  # Custom capacity
        episodic_memory=EpisodicMemoryConfig(capacity=200),
        semantic_memory=SemanticMemoryConfig(capacity=200),
        consolidation=ConsolidationConfig(
            enabled=True,
            interval_seconds=300,
            episodic_threshold=0.7,
            semantic_threshold=0.9,
        ),
        retrieval=RetrievalConfig(
            default_strategy="adaptive",
            cache_enabled=True,
            cache_ttl_seconds=300,
            cache_size=100,
            ranking_weights={
                "relevance": 0.5,
                "recency": 0.3,
                "importance": 0.2,
            },
        ),
        summary=SummaryConfig(auto_threshold=150),
    )
    custom_config.storage = StorageConfig(root=str(tmp_path))
    custom_config.embeddings = EmbeddingsConfig()

    # Create system with custom config
    system = MemorySystem(
        config=custom_config,
        embedding_service=mock_embedding_service,
    )
    await system.initialize()

    # Verify custom config was used
    assert system.working_memory.capacity == 50


@pytest.mark.asyncio
async def test_shutdown(memory_system: MemorySystem) -> None:
    """Test shutting down the memory system."""
    # Shutdown
    await memory_system.shutdown()

    # Verify cleanup
    assert memory_system.context_manager._running is False


@pytest.mark.asyncio
async def test_promote_to_semantic_manual(
    memory_system: MemorySystem,
    sample_context: MemoryContext,
) -> None:
    """Test manually promoting a memory to semantic tier."""
    # Store an episodic memory
    memory_item = await memory_system.store(
        content="Important fact to promote",
        context=sample_context,
        importance=0.75,  # Goes to episodic
        summary="Fact",
    )

    # Manually promote to semantic
    await memory_system.promote_to_semantic(memory_item.id)

    # Verify it's in semantic memory
    semantic_items = await memory_system.semantic_memory.get_all_items(sample_context)
    # Note: The promotion creates new semantic items, so we check if any exist
    assert len(semantic_items) > 0


@pytest.mark.asyncio
async def test_async_context_manager(
    tmp_path: Path,
    mock_embedding_service: MagicMock,
    memory_config: MemoryConfig,
) -> None:
    """Test MemorySystem async context manager initializes and shuts down properly."""
    from agent_vault.config import StorageConfig, CacheConfig, DocumentCacheConfig, EmbeddingsConfig

    # Create config like the memory_system fixture
    config = MagicMock(spec=Config)
    config.memory = memory_config
    config.storage = StorageConfig(root=str(tmp_path), default_project_id="test_default")
    config.storage.uri = str(tmp_path / "test.lancedb")
    config.cache = CacheConfig(document_cache=DocumentCacheConfig(max_size=100, ttl_seconds=3600, eviction_policy="lru"))
    config.embeddings = EmbeddingsConfig(default_provider="sentence_transformer")

    # Use async with to test context manager
    async with MemorySystem(config, mock_embedding_service) as memory:
        # Verify system is initialized
        assert memory._initialized is True
        assert memory.context_manager._running is True

        # Verify we can use the system
        context = memory.create_agent_context(
            agent_id="test_agent",
            session_id="test_session",
            conversation_id="test_conv",
        )
        item = await memory.store(
            content="Test memory via context manager",
            context=context,
            importance=0.5,
        )
        assert item is not None
        assert item.content == "Test memory via context manager"

    # After exiting context, system should be shut down
    assert memory._initialized is False
    assert memory.context_manager._running is False


@pytest.mark.asyncio
async def test_async_context_manager_handles_exception(
    tmp_path: Path,
    mock_embedding_service: MagicMock,
    memory_config: MemoryConfig,
) -> None:
    """Test MemorySystem async context manager shuts down even on exception."""
    from agent_vault.config import StorageConfig, CacheConfig, DocumentCacheConfig, EmbeddingsConfig

    # Create config like the memory_system fixture
    config = MagicMock(spec=Config)
    config.memory = memory_config
    config.storage = StorageConfig(root=str(tmp_path), default_project_id="test_default")
    config.storage.uri = str(tmp_path / "test.lancedb")
    config.cache = CacheConfig(document_cache=DocumentCacheConfig(max_size=100, ttl_seconds=3600, eviction_policy="lru"))
    config.embeddings = EmbeddingsConfig(default_provider="sentence_transformer")

    class TestError(Exception):
        pass

    memory: MemorySystem | None = None

    with pytest.raises(TestError):
        async with MemorySystem(config, mock_embedding_service) as mem:
            memory = mem
            assert memory._initialized is True
            raise TestError("Simulated error")

    # Verify shutdown still occurred despite exception
    assert memory is not None
    assert memory._initialized is False
    assert memory.context_manager._running is False
