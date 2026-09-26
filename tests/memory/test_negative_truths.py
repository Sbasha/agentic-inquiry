import pytest
from unittest.mock import MagicMock, AsyncMock

from agentic_inquiry.memory.models import MemoryContext, MemoryItem, MemoryTier, MemoryStatus, RetrievalResult
from agentic_inquiry.memory.retrieval import RetrievalEngine

@pytest.mark.asyncio
async def test_retrieval_filtering():
    # Mock retrieval engine deps
    wm = MagicMock()
    em = MagicMock()
    sm = MagicMock()
    es = MagicMock()
    es.embed_async = AsyncMock(return_value=[0.1]*384)
    config = MagicMock()
    config.memory.retrieval.cache_enabled = False
    
    engine = RetrievalEngine(wm, em, sm, es, config)
    
    # Mock search results
    active_item = MemoryItem(
        id="1", content="Active", summary="Active", 
        context=MemoryContext("a","s","c"), importance=0.5, tier=MemoryTier.WORKING,
        creator_agent_id="a", modifier_agent_id="a", status=MemoryStatus.ACTIVE
    )
    negated_item = MemoryItem(
        id="2", content="Negated", summary="Negated", 
        context=MemoryContext("a","s","c"), importance=0.5, tier=MemoryTier.WORKING,
        creator_agent_id="a", modifier_agent_id="a", status=MemoryStatus.NEGATED
    )
    
    # Mock _search_relevance to return both
    engine._search_relevance = AsyncMock(return_value=[
        RetrievalResult(active_item, 0.9, MemoryTier.WORKING),
        RetrievalResult(negated_item, 0.8, MemoryTier.WORKING)
    ])
    
    # Test default (exclude history)
    results = await engine.retrieve("query", MemoryContext("a","s","c"), strategy="relevance")
    assert len(results) == 1
    assert results[0].item.id == "1"
    
    # Test include history
    results_hist = await engine.retrieve("query", MemoryContext("a","s","c"), strategy="relevance", include_history=True)
    assert len(results_hist) == 2
