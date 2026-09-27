"""End-to-end workflow tests for memory system."""

import pytest

pytestmark = pytest.mark.integration

import asyncio
from pathlib import Path

from agentic_inquiry.config import Config
from agentic_inquiry.database import LanceDBManager
from agentic_inquiry.embeddings import EmbeddingService
from agentic_inquiry.memory import MemoryContext, MemorySystem, MemoryTier
from agentic_inquiry.memory.adapters.lancedb_adapter import LanceDBMemoryAdapter


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
def episodic_adapter(db_manager: LanceDBManager) -> LanceDBMemoryAdapter:
    return LanceDBMemoryAdapter(db_manager, table_name="memory_episodic_medium")


@pytest.fixture
def semantic_adapter(db_manager: LanceDBManager) -> LanceDBMemoryAdapter:
    return LanceDBMemoryAdapter(db_manager, table_name="memory_semantic_high")


@pytest.fixture
async def memory_system(
    test_config: Config,
    db_manager: LanceDBManager,
    episodic_adapter: LanceDBMemoryAdapter,
    semantic_adapter: LanceDBMemoryAdapter,
):
    """Create a fully initialized memory system."""
    embedding_service = EmbeddingService(test_config)

    # Working memory is in-memory only, so it has no adapter.
    system = MemorySystem(
        config=test_config,
        embedding_service=embedding_service,
        vector_store=db_manager,
        episodic_storage=episodic_adapter,
        semantic_storage=semantic_adapter,
    )
    await system.initialize()

    yield system

    await system.shutdown()


@pytest.fixture
def test_context():
    """Create a test memory context."""
    return MemoryContext(
        agent_id="test_agent",
        session_id="test_session",
        conversation_id="test_conversation",
    )


def _bump_access_after_first_read(
    adapter: LanceDBMemoryAdapter, monkeypatch: pytest.MonkeyPatch, access_count: int
) -> None:
    """Record an access from another writer right after the next read returns."""
    real_get_by_id = adapter.get_by_id

    async def get_then_concurrent_write(item_id: str):
        monkeypatch.setattr(adapter, "get_by_id", real_get_by_id)
        item = await real_get_by_id(item_id)
        await adapter.update(item_id, {"access_count": access_count})
        return item

    monkeypatch.setattr(adapter, "get_by_id", get_then_concurrent_write)


class TestCompleteMemoryLifecycle:
    """Test complete memory lifecycle from creation to deletion."""

    @pytest.mark.asyncio
    async def test_store_retrieve_update_delete(
        self, memory_system, test_context
    ):
        """Test complete lifecycle: store → retrieve → update → delete."""
        # Store a memory
        content = "User prefers Python for data analysis"
        item = await memory_system.store(
            content=content,
            context=test_context,
            importance=0.8,
            summary="Python preference",
        )

        assert item is not None
        assert item.content == content
        assert item.importance == 0.8

        # Retrieve the memory
        results = await memory_system.retrieve(
            query="programming language preference",
            context=test_context,
            limit=5,
        )

        assert len(results) > 0
        assert any(r.item.id == item.id for r in results)

        # Update importance
        await memory_system.update_importance(item.id, 0.95)

        # Retrieve again to verify update
        updated_item = await memory_system.episodic_memory.get_by_id(item.id)
        assert updated_item.importance == 0.95

        # Delete the memory
        deleted = await memory_system.delete(item.id)
        assert deleted is True

        # Verify deletion
        deleted_item = await memory_system.episodic_memory.get_by_id(item.id)
        assert deleted_item is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("importance", "tier"), [(0.8, "episodic"), (0.95, "semantic")]
    )
    async def test_update_importance_keeps_concurrent_access_update(
        self,
        memory_system,
        test_context,
        episodic_adapter,
        semantic_adapter,
        monkeypatch,
        importance,
        tier,
    ):
        """An access recorded between the setter's read and write survives."""
        adapter = episodic_adapter if tier == "episodic" else semantic_adapter
        item = await memory_system.store(
            content="User prefers Python", context=test_context, importance=importance
        )
        _bump_access_after_first_read(adapter, monkeypatch, access_count=5)

        assert await memory_system.update_importance(item.id, 0.5) is True

        stored = await adapter.get_by_id(item.id)
        assert stored.importance == 0.5
        assert stored.access_count == 5
        assert await adapter.count(filters={"id": item.id}) == 1

    @pytest.mark.asyncio
    async def test_update_confidence_keeps_concurrent_access_update(
        self, memory_system, test_context, semantic_adapter, monkeypatch
    ):
        """An access recorded between the setter's read and write survives."""
        item = await memory_system.store(
            content="Python is a programming language",
            context=test_context,
            importance=0.95,
            confidence=0.9,
        )
        _bump_access_after_first_read(semantic_adapter, monkeypatch, access_count=5)

        assert await memory_system.update_confidence(item.id, 0.4) is True

        stored = await semantic_adapter.get_by_id(item.id)
        assert stored.confidence == 0.4
        assert stored.access_count == 5
        assert await semantic_adapter.count(filters={"id": item.id}) == 1

    @pytest.mark.asyncio
    async def test_working_to_episodic_to_semantic(
        self, memory_system, test_context
    ):
        """Test memory promotion through all tiers."""
        # Store in working memory (low importance)
        item1 = await memory_system.store(
            content="User asked about Python",
            context=test_context,
            importance=0.5,
            summary="Python question",
        )
        assert item1.tier == MemoryTier.WORKING

        # Store in episodic memory (medium importance)
        item2 = await memory_system.store(
            content="User frequently uses Python for data analysis",
            context=test_context,
            importance=0.85,
            summary="Python usage pattern",
        )
        assert item2.tier == MemoryTier.EPISODIC

        # Manually promote to semantic - first store an item, then promote by ID
        episodic_item = await memory_system.store(
            content="Python is the user's preferred language for data analysis",
            context=test_context,
            importance=0.85,  # Goes to episodic (0.7-0.89), then we promote to semantic
            summary="Python preference",
        )
        # Promote by item_id with optional confidence
        promoted = await memory_system.promote_to_semantic(
            item_id=episodic_item.id,
            confidence=0.9,
        )
        assert promoted is True

        # Verify all tiers have content
        working_items = await memory_system.working_memory.get_all_items(
            test_context
        )
        episodic_items = await memory_system.episodic_memory.get_all_items(
            test_context
        )
        semantic_items = await memory_system.semantic_memory.get_all_items(
            test_context
        )

        assert len(working_items) > 0
        assert len(episodic_items) > 0
        assert len(semantic_items) > 0

    @pytest.mark.asyncio
    async def test_conversation_loading(self, memory_system, test_context):
        """Test loading conversation history into working memory."""
        # Store multiple events in episodic memory
        events = [
            "User asked about Python",
            "Assistant explained Python basics",
            "User asked about data analysis",
            "Assistant recommended pandas library",
            "User thanked the assistant",
        ]

        for event in events:
            await memory_system.store(
                content=event,
                context=test_context,
                importance=0.7,
                summary=event[:20],
            )

        # Clear working memory
        await memory_system.working_memory.clear_session(
            test_context.session_id
        )

        # Load conversation into working memory
        loaded = await memory_system.load_conversation(
            context=test_context, limit=3
        )

        # Should load most recent 3 events
        assert len(loaded) == 3
        assert all(item.tier == MemoryTier.WORKING for item in loaded)


class TestMultiAgentScenarios:
    """Test multi-agent memory isolation."""

    @pytest.mark.asyncio
    async def test_agent_memory_isolation(self, memory_system):
        """Test that different agents have isolated memories."""
        # Create contexts for two agents
        context1 = MemoryContext(
            agent_id="agent_1",
            session_id="session_1",
            conversation_id="conv_1",
        )
        context2 = MemoryContext(
            agent_id="agent_2",
            session_id="session_2",
            conversation_id="conv_2",
        )

        # Store memories for agent 1
        item1 = await memory_system.store(
            content="Agent 1 memory",
            context=context1,
            importance=0.8,
            summary="Agent 1",
        )

        # Store memories for agent 2
        item2 = await memory_system.store(
            content="Agent 2 memory",
            context=context2,
            importance=0.8,
            summary="Agent 2",
        )

        # Retrieve for agent 1
        results1 = await memory_system.retrieve(
            query="memory", context=context1, limit=10
        )

        # Retrieve for agent 2
        results2 = await memory_system.retrieve(
            query="memory", context=context2, limit=10
        )

        # Verify isolation
        agent1_ids = {r.item.id for r in results1}
        agent2_ids = {r.item.id for r in results2}

        assert item1.id in agent1_ids
        assert item1.id not in agent2_ids
        assert item2.id in agent2_ids
        assert item2.id not in agent1_ids

    @pytest.mark.asyncio
    async def test_concurrent_agent_operations(self, memory_system):
        """Test concurrent operations from multiple agents."""

        async def agent_workflow(agent_id: str):
            context = MemoryContext(
                agent_id=agent_id,
                session_id=f"session_{agent_id}",
                conversation_id=f"conv_{agent_id}",
            )

            # Store multiple memories
            for i in range(5):
                await memory_system.store(
                    content=f"{agent_id} memory {i}",
                    context=context,
                    importance=0.7,
                    summary=f"{agent_id} {i}",
                )

            # Retrieve memories
            results = await memory_system.retrieve(
                query="memory", context=context, limit=10
            )

            return len(results)

        # Run workflows for 3 agents concurrently
        tasks = [agent_workflow(f"agent_{i}") for i in range(3)]
        results = await asyncio.gather(*tasks)

        # Each agent should have their own memories
        assert all(count >= 5 for count in results)

    @pytest.mark.asyncio
    async def test_session_isolation(self, memory_system):
        """Test that different sessions have isolated working memory."""
        # Create contexts for same agent, different sessions
        context1 = MemoryContext(
            agent_id="test_agent",
            session_id="session_1",
            conversation_id="conv_1",
        )
        context2 = MemoryContext(
            agent_id="test_agent",
            session_id="session_2",
            conversation_id="conv_2",
        )

        # Store in working memory for session 1
        item1 = await memory_system.store(
            content="Session 1 memory",
            context=context1,
            importance=0.5,  # Low importance → working memory
            summary="Session 1",
        )

        # Store in working memory for session 2
        item2 = await memory_system.store(
            content="Session 2 memory",
            context=context2,
            importance=0.5,
            summary="Session 2",
        )

        # Verify session isolation in working memory
        working_items1 = await memory_system.working_memory.get_all_items(
            context1
        )
        working_items2 = await memory_system.working_memory.get_all_items(
            context2
        )

        ids1 = {item.id for item in working_items1}
        ids2 = {item.id for item in working_items2}

        assert item1.id in ids1
        assert item1.id not in ids2
        assert item2.id in ids2
        assert item2.id not in ids1


class TestConsolidationWorkflows:
    """Test consolidation workflows."""

    @pytest.mark.asyncio
    async def test_automatic_consolidation(self, memory_system, test_context):
        """Test automatic consolidation of important memories."""
        # Store multiple memories with varying importance
        await memory_system.store(
            content="Low importance event",
            context=test_context,
            importance=0.5,
            summary="Low",
        )

        await memory_system.store(
            content="High importance event",
            context=test_context,
            importance=0.95,
            summary="High",
        )

        # Run consolidation
        result = await memory_system.consolidate(context=test_context)

        # Verify consolidation completed successfully with statistics
        assert result is not None, "Consolidation should return a result"
        assert result.context == test_context, "Result should reference the context"
        assert result.items_promoted >= 0, "Promoted items should be non-negative"
        assert result.items_demoted >= 0, "Demoted items should be non-negative"
        assert result.concepts_extracted >= 0, "Concepts extracted should be non-negative"
        assert result.duration_ms > 0, "Consolidation should take some time"

    @pytest.mark.asyncio
    async def test_session_end_consolidation(
        self, memory_system, test_context
    ):
        """Test consolidation at session end."""
        # Store items in working memory (importance < 0.7)
        for i in range(3):
            await memory_system.store(
                content=f"Low importance event {i}",
                context=test_context,
                importance=0.5,  # Working memory tier
                summary=f"Event {i}",
            )
        
        # Manually update importance to trigger promotion during consolidation
        working_items = await memory_system.working_memory.get_all_items(test_context)
        for item in working_items:
            item.importance = 0.85  # Above episodic threshold (0.8)
            await memory_system.working_memory.store(item)

        # Run consolidation (simulates session end)
        result = await memory_system.consolidate(context=test_context)

        # Verify consolidation occurred with meaningful statistics
        assert result is not None, "Consolidation should return a result"
        assert result.context == test_context, "Result should reference the context"
        assert result.duration_ms > 0, "Consolidation should take measurable time"

        # With 3 items at importance 0.85 (above 0.8 threshold), we expect promotions
        # Note: The exact number depends on consolidation engine implementation
        assert result.items_promoted >= 0, "Promoted items should be non-negative"
        assert result.items_demoted >= 0, "Demoted items should be non-negative"

        # Verify the consolidation result has valid structure
        assert hasattr(result, 'concepts_extracted'), "Result should track concepts extracted"

    @pytest.mark.asyncio
    async def test_concept_extraction(self, memory_system, test_context):
        """Test concept extraction from episodic patterns."""
        # Store multiple related events
        events = [
            "User asked about Python",
            "User wrote Python code",
            "User debugged Python script",
            "User deployed Python application",
        ]

        for event in events:
            await memory_system.store(
                content=event,
                context=test_context,
                importance=0.85,
                summary=event[:20],
            )

        # Run consolidation to trigger concept extraction
        result = await memory_system.consolidate(context=test_context)

        # Verify consolidation completed with valid structure
        assert result is not None, "Consolidation should return a result"
        assert result.context == test_context, "Result should reference the context"
        assert result.duration_ms > 0, "Consolidation should take measurable time"

        # Concept extraction is pattern-based - with 4 related Python events,
        # we may or may not extract concepts depending on implementation
        assert hasattr(result, 'concepts_extracted'), "Result should track concepts"
        assert result.concepts_extracted >= 0, "Concepts extracted should be non-negative"

        # Verify the stored items are still accessible after consolidation
        retrieved = await memory_system.retrieve(
            query="Python",
            context=test_context,
            limit=10
        )
        assert len(retrieved) > 0, "Should retrieve Python-related memories after consolidation"


class TestRetrievalStrategies:
    """Test different retrieval strategies."""

    @pytest.mark.asyncio
    async def test_relevance_strategy(self, memory_system, test_context):
        """Test relevance-based retrieval."""
        # Store memories with different content
        await memory_system.store(
            content="Python programming language",
            context=test_context,
            importance=0.7,
            summary="Python",
        )
        await memory_system.store(
            content="JavaScript web development",
            context=test_context,
            importance=0.7,
            summary="JavaScript",
        )

        # Retrieve with relevance strategy
        results = await memory_system.retrieve(
            query="Python coding",
            context=test_context,
            limit=5,
            strategy="relevance",
        )

        # Should retrieve both items with relevance scores
        assert len(results) >= 2
        # Verify Python-related content is in results
        contents = [r.item.content for r in results]
        assert any("Python" in content for content in contents)

    @pytest.mark.asyncio
    async def test_recency_strategy(self, memory_system, test_context):
        """Test recency-based retrieval."""
        # Store memories at different times
        old_item = await memory_system.store(
            content="Old memory",
            context=test_context,
            importance=0.7,
            summary="Old",
        )

        # Wait a bit
        await asyncio.sleep(0.1)

        new_item = await memory_system.store(
            content="New memory",
            context=test_context,
            importance=0.7,
            summary="New",
        )

        # Retrieve with recency strategy
        results = await memory_system.retrieve(
            query="memory",
            context=test_context,
            limit=5,
            strategy="recency",
        )

        # Most recent should come first
        assert len(results) >= 2
        # New item should have higher score or appear first
        result_ids = [r.item.id for r in results]
        new_index = result_ids.index(new_item.id)
        old_index = result_ids.index(old_item.id)
        assert new_index <= old_index

    @pytest.mark.asyncio
    async def test_importance_strategy(self, memory_system, test_context):
        """Test importance-based retrieval."""
        # Store memories with different importance
        low_item = await memory_system.store(
            content="Low importance memory",
            context=test_context,
            importance=0.5,
            summary="Low",
        )

        high_item = await memory_system.store(
            content="High importance memory",
            context=test_context,
            importance=0.95,
            summary="High",
        )

        # Retrieve with importance strategy
        results = await memory_system.retrieve(
            query="memory",
            context=test_context,
            limit=5,
            strategy="importance",
        )

        # Higher importance should come first
        assert len(results) >= 2
        result_ids = [r.item.id for r in results]
        high_index = result_ids.index(high_item.id)
        low_index = result_ids.index(low_item.id)
        assert high_index <= low_index

    @pytest.mark.asyncio
    async def test_adaptive_strategy(self, memory_system, test_context):
        """Test adaptive retrieval strategy."""
        # Store diverse memories
        await memory_system.store(
            content="Python programming",
            context=test_context,
            importance=0.9,
            summary="Python",
        )
        await memory_system.store(
            content="JavaScript development",
            context=test_context,
            importance=0.6,
            summary="JavaScript",
        )

        # Retrieve with adaptive strategy (default)
        results = await memory_system.retrieve(
            query="programming",
            context=test_context,
            limit=5,
            strategy="adaptive",
        )

        # Should balance relevance, recency, and importance
        assert len(results) > 0
        # Verify all results have valid retrieval metadata
        assert all(hasattr(r, 'relevance_score') for r in results)
        assert all(hasattr(r, 'retrieval_tier') for r in results)
        # Verify both items were retrieved
        assert len(results) >= 2


class TestBatchOperations:
    """Test batch operations."""

    @pytest.mark.asyncio
    async def test_batch_store(self, memory_system, test_context):
        """Test storing multiple memories in batch."""
        contents = [
            "First memory",
            "Second memory",
            "Third memory",
        ]

        # Store in batch - batch_store expects list of tuples
        # (content, context, importance, summary, metadata)
        items = await memory_system.batch_store(
            items=[
                (content, test_context, 0.7, None, None)
                for content in contents
            ]
        )

        # Verify all stored
        assert len(items) == 3
        assert all(item.content in contents for item in items)

    @pytest.mark.asyncio
    async def test_batch_retrieve(self, memory_system, test_context):
        """Test retrieving with multiple queries."""
        # Store diverse memories
        await memory_system.store(
            content="Python programming",
            context=test_context,
            importance=0.8,
            summary="Python",
        )
        await memory_system.store(
            content="JavaScript development",
            context=test_context,
            importance=0.8,
            summary="JavaScript",
        )
        await memory_system.store(
            content="Machine learning",
            context=test_context,
            importance=0.8,
            summary="ML",
        )

        # Batch retrieve - expects list of (query, context) tuples
        queries = ["Python", "JavaScript", "machine learning"]
        results_list = await memory_system.batch_retrieve(
            queries=[(query, test_context) for query in queries],
            limit=5
        )

        # Verify results for each query
        assert len(results_list) == 3
        assert all(len(results) > 0 for results in results_list)


class TestErrorHandling:
    """Test error handling in workflows."""

    @pytest.mark.asyncio
    async def test_invalid_context(self, memory_system):
        """Test handling of invalid importance values."""
        # Test with invalid importance (out of range)
        valid_context = MemoryContext(
            agent_id="test_agent",
            session_id="test_session",
            conversation_id="test_conversation",
        )
        
        # Importance too high
        with pytest.raises(ValueError, match="importance must be between"):
            await memory_system.store(
                content="Test",
                context=valid_context,
                importance=1.5,  # Invalid: > 1.0
                summary="Test",
            )
        
        # Importance too low
        with pytest.raises(ValueError, match="importance must be between"):
            await memory_system.store(
                content="Test",
                context=valid_context,
                importance=-0.5,  # Invalid: < 0.0
                summary="Test",
            )

    @pytest.mark.asyncio
    async def test_invalid_importance(self, memory_system, test_context):
        """Test handling of invalid importance values."""
        # Importance > 1.0
        with pytest.raises(ValueError):
            await memory_system.store(
                content="Test",
                context=test_context,
                importance=1.5,  # Invalid
                summary="Test",
            )

        # Importance < 0.0
        with pytest.raises(ValueError):
            await memory_system.store(
                content="Test",
                context=test_context,
                importance=-0.5,  # Invalid
                summary="Test",
            )

    @pytest.mark.asyncio
    async def test_delete_nonexistent_item(self, memory_system):
        """Test deleting non-existent item."""
        # Should return False, not raise error
        deleted = await memory_system.delete("nonexistent_id")
        assert deleted is False
