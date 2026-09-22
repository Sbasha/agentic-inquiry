"""
Tests for RetrievalEngine.
"""

import pytest

pytestmark = pytest.mark.integration

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from agent_vault.config import Config, RetrievalConfig
from agent_vault.database.lancedb_manager import LanceDBManager
from agent_vault.memory.adapters.lancedb_adapter import LanceDBMemoryAdapter
from agent_vault.memory.layers.episodic import EpisodicMemory
from agent_vault.memory.layers.semantic import SemanticMemory
from agent_vault.memory.layers.working import WorkingMemory
from agent_vault.memory.models import (
    MemoryContext,
    MemoryItem,
    MemoryTier,
    RetrievalResult,
)
from agent_vault.memory.retrieval import RetrievalEngine


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
    return LanceDBMemoryAdapter(db_manager, table_name="memory_episodic_medium")


@pytest.fixture
async def semantic_adapter(db_manager: LanceDBManager) -> LanceDBMemoryAdapter:
    """Create a LanceDB memory adapter for semantic memory."""
    return LanceDBMemoryAdapter(db_manager, table_name="memory_semantic_high")


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
    service.embed_async = AsyncMock(return_value=np.random.rand(384).astype(np.float32))
    return service


@pytest.fixture
def retrieval_config() -> RetrievalConfig:
    """Create a retrieval configuration."""
    return RetrievalConfig(
        default_strategy="adaptive",
        cache_enabled=True,
        cache_ttl_seconds=300,
        cache_size=1000,
        ranking_weights={
            "relevance": 0.5,
            "recency": 0.3,
            "importance": 0.2,
        },
    )


@pytest.fixture
def retrieval_engine(
    working_memory: WorkingMemory,
    episodic_memory: EpisodicMemory,
    semantic_memory: SemanticMemory,
    mock_embedding_service: MagicMock,
    retrieval_config: RetrievalConfig,
) -> RetrievalEngine:
    """Create a retrieval engine."""
    # Create a mock Config with proper structure
    from unittest.mock import MagicMock
    from agent_vault.config import Config, MemoryConfig
    
    config = MagicMock(spec=Config)
    config.memory = MagicMock(spec=MemoryConfig)
    config.memory.retrieval = retrieval_config
    
    return RetrievalEngine(
        working_memory=working_memory,
        episodic_memory=episodic_memory,
        semantic_memory=semantic_memory,
        embedding_service=mock_embedding_service,
        config=config,
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
async def test_retrieval_engine_initialization(
    retrieval_engine: RetrievalEngine,
) -> None:
    """Test retrieval engine initialization."""
    assert retrieval_engine._cache_enabled is True
    assert retrieval_engine._cache_ttl_seconds == 300
    assert retrieval_engine._cache_size == 1000


@pytest.mark.asyncio
async def test_retrieve_relevance_strategy(
    retrieval_engine: RetrievalEngine,
    working_memory: WorkingMemory,
    sample_context: MemoryContext,
) -> None:
    """Test retrieval with relevance strategy."""
    # Add items to working memory
    base_embedding = np.random.rand(384).astype(np.float32)
    for i in range(3):
        embedding = base_embedding + np.random.rand(384).astype(np.float32) * 0.1
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Content {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.7,
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=embedding,
        )
        await working_memory.store(item)

    # Retrieve with relevance strategy
    results = await retrieval_engine.retrieve(
        query="test query",
        context=sample_context,
        strategy="relevance",
        limit=10,
    )

    # Verify results
    assert len(results) > 0
    assert all(r.retrieval_tier == MemoryTier.WORKING for r in results)
    # Results should be sorted by relevance score
    scores = [r.relevance_score for r in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_retrieve_recency_strategy(
    retrieval_engine: RetrievalEngine,
    working_memory: WorkingMemory,
    sample_context: MemoryContext,
) -> None:
    """Test retrieval with recency strategy."""
    # Add items to working memory with different timestamps
    for i in range(3):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Content {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.7,
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
        )
        await working_memory.store(item)

    # Retrieve with recency strategy
    results = await retrieval_engine.retrieve(
        query="test query",
        context=sample_context,
        strategy="recency",
        limit=10,
    )

    # Verify results
    assert len(results) > 0
    # More recent items should have higher scores
    assert all(r.relevance_score > 0 for r in results)


@pytest.mark.asyncio
async def test_retrieve_importance_strategy(
    retrieval_engine: RetrievalEngine,
    working_memory: WorkingMemory,
    sample_context: MemoryContext,
) -> None:
    """Test retrieval with importance strategy."""
    # Add items with varying importance
    for i in range(3):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Content {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.5 + (i * 0.2),  # 0.5, 0.7, 0.9
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
        )
        await working_memory.store(item)

    # Retrieve with importance strategy
    results = await retrieval_engine.retrieve(
        query="test query",
        context=sample_context,
        strategy="importance",
        limit=10,
    )

    # Verify results
    assert len(results) > 0
    # Higher importance items should have higher scores
    assert all(r.relevance_score > 0 for r in results)


@pytest.mark.asyncio
async def test_retrieve_adaptive_strategy(
    retrieval_engine: RetrievalEngine,
    working_memory: WorkingMemory,
    sample_context: MemoryContext,
) -> None:
    """Test retrieval with adaptive strategy."""
    # Add items to working memory
    for i in range(3):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Content {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.7 + (i * 0.1),
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
        )
        await working_memory.store(item)

    # Retrieve with adaptive strategy
    results = await retrieval_engine.retrieve(
        query="test query",
        context=sample_context,
        strategy="adaptive",
        limit=10,
    )

    # Verify results
    assert len(results) > 0
    # Scores should combine relevance, recency, and importance
    assert all(r.relevance_score > 0 for r in results)


@pytest.mark.asyncio
async def test_retrieve_multi_tier_search(
    retrieval_engine: RetrievalEngine,
    working_memory: WorkingMemory,
    episodic_memory: EpisodicMemory,
    semantic_memory: SemanticMemory,
    sample_context: MemoryContext,
) -> None:
    """Test retrieval across multiple memory tiers."""
    # Add items to working memory
    working_item = MemoryItem(
        id=str(uuid.uuid4()),
        content="Working memory content",
        summary="Working summary",
        context=sample_context,
        importance=0.7,
        tier=MemoryTier.WORKING,
        creator_agent_id="test_agent",
        modifier_agent_id="test_agent",
        embedding=np.random.rand(384).astype(np.float32),
    )
    await working_memory.store(working_item)

    # Add items to episodic memory
    episodic_item = MemoryItem(
        id=str(uuid.uuid4()),
        content="Episodic memory content",
        summary="Episodic summary",
        context=sample_context,
        importance=0.8,
        tier=MemoryTier.EPISODIC,
        creator_agent_id="test_agent",
        modifier_agent_id="test_agent",
        embedding=np.random.rand(384).astype(np.float32),
        summary_embedding=np.random.rand(384).astype(np.float32),
        event_type="test_event",
    )
    await episodic_memory.store(episodic_item)

    # Add items to semantic memory
    semantic_item = MemoryItem(
        id=str(uuid.uuid4()),
        content="Semantic memory content",
        summary="Semantic summary",
        context=sample_context,
        importance=0.9,
        tier=MemoryTier.SEMANTIC,
        creator_agent_id="test_agent",
        modifier_agent_id="test_agent",
        embedding=np.random.rand(384).astype(np.float32),
        summary_embedding=np.random.rand(384).astype(np.float32),
        subject="test",
        relationship="is_a",
        object="concept",
        confidence=0.9,
    )
    await semantic_memory.store(semantic_item)

    # Retrieve across all tiers
    results = await retrieval_engine.retrieve(
        query="test query",
        context=sample_context,
        strategy="adaptive",
        limit=10,
    )

    # Verify results from multiple tiers
    assert len(results) >= 3
    tiers = {r.retrieval_tier for r in results}
    assert MemoryTier.WORKING in tiers
    assert MemoryTier.EPISODIC in tiers
    assert MemoryTier.SEMANTIC in tiers


@pytest.mark.asyncio
async def test_retrieve_respects_limit(
    retrieval_engine: RetrievalEngine,
    working_memory: WorkingMemory,
    sample_context: MemoryContext,
) -> None:
    """Test that retrieval respects the limit parameter."""
    # Add many items
    for i in range(10):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Content {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.7,
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
        )
        await working_memory.store(item)

    # Retrieve with limit
    results = await retrieval_engine.retrieve(
        query="test query",
        context=sample_context,
        strategy="relevance",
        limit=5,
    )

    # Verify limit is respected
    assert len(results) <= 5


@pytest.mark.asyncio
async def test_retrieve_filters_by_context(
    retrieval_engine: RetrievalEngine,
    working_memory: WorkingMemory,
) -> None:
    """Test that retrieval filters by agent_id."""
    # Add items for different agents
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
            content=f"Agent1 content {i}",
            summary=f"Summary {i}",
            context=agent1_context,
            importance=0.7,
            tier=MemoryTier.WORKING,
            creator_agent_id="agent1",
            modifier_agent_id="agent1",
            embedding=np.random.rand(384).astype(np.float32),
        )
        await working_memory.store(item)

    # Store items for agent2
    for i in range(2):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Agent2 content {i}",
            summary=f"Summary {i}",
            context=agent2_context,
            importance=0.7,
            tier=MemoryTier.WORKING,
            creator_agent_id="agent2",
            modifier_agent_id="agent2",
            embedding=np.random.rand(384).astype(np.float32),
        )
        await working_memory.store(item)

    # Retrieve for agent1
    results = await retrieval_engine.retrieve(
        query="test query",
        context=agent1_context,
        strategy="relevance",
        limit=10,
    )

    # Verify only agent1 items are returned
    assert len(results) == 3
    assert all(r.item.context.agent_id == "agent1" for r in results)


@pytest.mark.asyncio
async def test_query_caching(
    retrieval_engine: RetrievalEngine,
    working_memory: WorkingMemory,
    sample_context: MemoryContext,
) -> None:
    """Test that query results are cached."""
    # Add items to working memory
    for i in range(3):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Content {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.7,
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
        )
        await working_memory.store(item)

    # First retrieval (should cache)
    results1 = await retrieval_engine.retrieve(
        query="test query",
        context=sample_context,
        strategy="relevance",
        limit=10,
    )

    # Get stats
    stats = retrieval_engine.get_retrieval_stats()
    initial_cache_hits = stats["cache_hits"]

    # Second retrieval (should hit cache)
    results2 = await retrieval_engine.retrieve(
        query="test query",
        context=sample_context,
        strategy="relevance",
        limit=10,
    )

    # Verify cache was used
    stats = retrieval_engine.get_retrieval_stats()
    assert stats["cache_hits"] > initial_cache_hits

    # Results should be the same
    assert len(results1) == len(results2)


@pytest.mark.asyncio
async def test_batch_retrieve(
    retrieval_engine: RetrievalEngine,
    working_memory: WorkingMemory,
    sample_context: MemoryContext,
) -> None:
    """Test batch retrieval for multiple queries."""
    # Add items to working memory
    for i in range(5):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Content {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.7,
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
        )
        await working_memory.store(item)

    # Batch retrieve
    queries = [
        ("query 1", sample_context),
        ("query 2", sample_context),
        ("query 3", sample_context),
    ]
    results = await retrieval_engine.batch_retrieve(
        queries=queries,
        strategy="relevance",
        limit=10,
    )

    # Verify results
    assert len(results) == 3
    assert all(isinstance(r, list) for r in results)
    assert all(len(r) > 0 for r in results)


@pytest.mark.asyncio
async def test_get_retrieval_stats(
    retrieval_engine: RetrievalEngine,
) -> None:
    """Test getting retrieval statistics."""
    stats = retrieval_engine.get_retrieval_stats()

    assert "total_queries" in stats
    assert "cache_hits" in stats
    assert "cache_misses" in stats
    assert "cache_size" in stats
    assert "cache_hit_rate" in stats
    assert "queries_by_strategy" in stats


@pytest.mark.asyncio
async def test_retrieve_with_disabled_cache(
    working_memory: WorkingMemory,
    episodic_memory: EpisodicMemory,
    semantic_memory: SemanticMemory,
    mock_embedding_service: MagicMock,
    sample_context: MemoryContext,
) -> None:
    """Test retrieval with caching disabled."""
    # Create engine with caching disabled
    from agent_vault.config import Config, MemoryConfig
    
    retrieval_config = RetrievalConfig(
        default_strategy="adaptive",
        cache_enabled=False,
        cache_ttl_seconds=300,
        cache_size=100,
        ranking_weights={
            "relevance": 0.5,
            "recency": 0.3,
            "importance": 0.2,
        },
    )
    
    config = MagicMock(spec=Config)
    config.memory = MagicMock(spec=MemoryConfig)
    config.memory.retrieval = retrieval_config
    
    engine = RetrievalEngine(
        working_memory=working_memory,
        episodic_memory=episodic_memory,
        semantic_memory=semantic_memory,
        embedding_service=mock_embedding_service,
        config=config,
    )

    # Add items
    for i in range(3):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=f"Content {i}",
            summary=f"Summary {i}",
            context=sample_context,
            importance=0.7,
            tier=MemoryTier.WORKING,
            creator_agent_id="test_agent",
            modifier_agent_id="test_agent",
            embedding=np.random.rand(384).astype(np.float32),
        )
        await working_memory.store(item)

    # Retrieve multiple times
    await engine.retrieve("test query", sample_context, "relevance", 10)
    await engine.retrieve("test query", sample_context, "relevance", 10)

    # Verify cache was not used
    stats = engine.get_retrieval_stats()
    assert stats["cache_hits"] == 0
    assert stats["cache_enabled"] is False


@pytest.mark.asyncio
async def test_retrieve_empty_results(
    retrieval_engine: RetrievalEngine,
    sample_context: MemoryContext,
) -> None:
    """Test retrieval with no matching items."""
    # Retrieve without any items stored
    results = await retrieval_engine.retrieve(
        query="test query",
        context=sample_context,
        strategy="relevance",
        limit=10,
    )

    # Should return empty list
    assert len(results) == 0


@pytest.mark.asyncio
async def test_ranking_algorithm(
    retrieval_engine: RetrievalEngine,
    working_memory: WorkingMemory,
    sample_context: MemoryContext,
) -> None:
    """Test that ranking algorithm combines multiple factors."""
    # Add items with different characteristics
    items = []
    
    # High relevance, low importance
    item1 = MemoryItem(
        id=str(uuid.uuid4()),
        content="Highly relevant content",
        summary="Summary 1",
        context=sample_context,
        importance=0.5,
        tier=MemoryTier.WORKING,
        creator_agent_id="test_agent",
        modifier_agent_id="test_agent",
        embedding=np.random.rand(384).astype(np.float32),
    )
    items.append(item1)
    
    # Low relevance, high importance
    item2 = MemoryItem(
        id=str(uuid.uuid4()),
        content="Less relevant content",
        summary="Summary 2",
        context=sample_context,
        importance=0.95,
        tier=MemoryTier.WORKING,
        creator_agent_id="test_agent",
        modifier_agent_id="test_agent",
        embedding=np.random.rand(384).astype(np.float32),
    )
    items.append(item2)

    for item in items:
        await working_memory.store(item)

    # Retrieve with adaptive strategy
    results = await retrieval_engine.retrieve(
        query="test query",
        context=sample_context,
        strategy="adaptive",
        limit=10,
    )

    # Verify results are ranked
    assert len(results) == 2
    assert all(r.relevance_score > 0 for r in results)
    # Scores should reflect combined factors from adaptive weighting
    weights = retrieval_engine.config.memory.retrieval.ranking_weights
    if isinstance(weights, dict):
        weight_map = weights
    else:
        weight_map = {
            "relevance": getattr(weights, "relevance"),
            "recency": getattr(weights, "recency"),
            "importance": getattr(weights, "importance"),
        }

    def adaptive_score(result: RetrievalResult) -> float:
        """Mirror RetrievalEngine adaptive scoring for verification."""
        relevance = result.relevance_score

        if result.retrieval_tier == MemoryTier.WORKING:
            recency = 1.0
        elif result.retrieval_tier == MemoryTier.EPISODIC:
            now = datetime.now(timezone.utc)
            age_seconds = (now - result.item.created_at).total_seconds()
            decay = max(0.0, 1.0 - (age_seconds / 604800))
            recency = 0.5 + (0.5 * decay)
        else:
            recency = 0.3

        importance = result.item.importance

        return (
            weight_map["relevance"] * relevance
            + weight_map["recency"] * recency
            + weight_map["importance"] * importance
        )

    adaptive_scores = [adaptive_score(r) for r in results]
    assert adaptive_scores == sorted(adaptive_scores, reverse=True)
