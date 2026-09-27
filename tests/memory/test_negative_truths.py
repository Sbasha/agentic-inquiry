import pytest
from unittest.mock import MagicMock, AsyncMock

from agentic_inquiry.memory.system import MemorySystem
from agentic_inquiry.memory.models import (
    MemoryContext,
    MemoryItem,
    MemoryTier,
    MemoryStatus,
    RetrievalResult,
)
from agentic_inquiry.memory.retrieval import RetrievalEngine
from agentic_inquiry.memory.protocols import MemoryStorageProtocol


@pytest.mark.asyncio
async def test_negate_memory():
    # Mock dependencies
    config = MagicMock()
    config.memory.retrieval.cache_enabled = False
    embedding_service = MagicMock()
    embedding_service.embed_async = AsyncMock(return_value=[0.1] * 384)

    # Mock storage adapter
    adapter = MagicMock(spec=MemoryStorageProtocol)
    adapter.retrieve = AsyncMock(return_value=[])

    # Create system with mocks
    system = MemorySystem(
        config, embedding_service, episodic_storage=adapter, semantic_storage=adapter
    )
    # Bypass initialization check
    system._initialized = True

    # Mock working memory behavior
    mock_item = MemoryItem(
        id="test_id",
        content="Test content",
        summary="Summary",
        context=MemoryContext("agent", "session", "conv"),
        importance=0.5,
        tier=MemoryTier.WORKING,
        creator_agent_id="agent",
        modifier_agent_id="agent",
    )

    system.working_memory.get_by_id = AsyncMock(return_value=mock_item)
    system.working_memory.store = AsyncMock()
    system.update_importance = AsyncMock(return_value=True)  # Pretend found

    # Execute negate
    result = await system.negate_memory("test_id")

    assert result is True
    assert mock_item.status == MemoryStatus.NEGATED
    system.working_memory.store.assert_called_with(mock_item)


@pytest.mark.asyncio
async def test_retrieval_filtering():
    # Mock retrieval engine deps
    wm = MagicMock()
    em = MagicMock()
    sm = MagicMock()
    es = MagicMock()
    es.embed_async = AsyncMock(return_value=[0.1] * 384)
    config = MagicMock()
    config.memory.retrieval.cache_enabled = False

    engine = RetrievalEngine(wm, em, sm, es, config)

    # Mock search results
    active_item = MemoryItem(
        id="1",
        content="Active",
        summary="Active",
        context=MemoryContext("a", "s", "c"),
        importance=0.5,
        tier=MemoryTier.WORKING,
        creator_agent_id="a",
        modifier_agent_id="a",
        status=MemoryStatus.ACTIVE,
    )
    negated_item = MemoryItem(
        id="2",
        content="Negated",
        summary="Negated",
        context=MemoryContext("a", "s", "c"),
        importance=0.5,
        tier=MemoryTier.WORKING,
        creator_agent_id="a",
        modifier_agent_id="a",
        status=MemoryStatus.NEGATED,
    )

    # Mock _search_relevance to return both
    engine._search_relevance = AsyncMock(
        return_value=[
            RetrievalResult(active_item, 0.9, MemoryTier.WORKING),
            RetrievalResult(negated_item, 0.8, MemoryTier.WORKING),
        ]
    )

    # Test default (exclude history)
    results = await engine.retrieve(
        "query", MemoryContext("a", "s", "c"), strategy="relevance"
    )
    assert len(results) == 1
    assert results[0].item.id == "1"

    # Test include history
    results_hist = await engine.retrieve(
        "query",
        MemoryContext("a", "s", "c"),
        strategy="relevance",
        include_history=True,
    )
    assert len(results_hist) == 2
