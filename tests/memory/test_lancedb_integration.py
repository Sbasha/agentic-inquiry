"""Integration tests for LanceDB with memory system."""

import pytest

pytestmark = pytest.mark.integration

import asyncio
import uuid
from pathlib import Path

from agentic_inquiry.config import Config
from agentic_inquiry.database import LanceDBManager
from agentic_inquiry.embeddings import EmbeddingService
from agentic_inquiry.memory import MemoryContext, MemoryItem, MemoryTier
from agentic_inquiry.memory.adapters.lancedb_adapter import LanceDBMemoryAdapter
from agentic_inquiry.memory.layers.episodic import EpisodicMemory
from agentic_inquiry.memory.layers.semantic import SemanticMemory


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
def embedding_service(test_config: Config) -> EmbeddingService:
    """Create an embedding service for testing."""
    return EmbeddingService(test_config)


@pytest.fixture
def test_context() -> MemoryContext:
    """Create a test memory context."""
    return MemoryContext(
        agent_id="test_agent",
        session_id="test_session",
        conversation_id="test_conversation",
    )


class TestLanceDBTableCreation:
    """Test LanceDB table creation and schema."""

    @pytest.mark.asyncio
    async def test_episodic_table_creation(
        self, episodic_adapter: LanceDBMemoryAdapter, embedding_service: EmbeddingService
    ):
        """Test episodic memory table is created and can store/retrieve data."""
        episodic = EpisodicMemory(storage=episodic_adapter, limit=100)
        await episodic.initialize()

        # Verify initialization succeeded
        assert episodic._initialized is True

        # Verify we can store and retrieve data
        context = MemoryContext(
            agent_id="test_agent",
            session_id="test_session",
            conversation_id="test_conversation",
        )
        embedding = await embedding_service.embed_async("test content")
        summary_embedding = await embedding_service.embed_async("test summary")

        item = MemoryItem(
            id=str(uuid.uuid4()),
            content="test content",
            summary="test summary",
            context=context,
            importance=0.8,
            tier=MemoryTier.EPISODIC,
            creator_agent_id=context.agent_id,
            modifier_agent_id=context.agent_id,
            event_type="test",
            embedding=embedding,
            summary_embedding=summary_embedding,
        )
        await episodic.store(item)

        # Verify retrieval works
        retrieved = await episodic.get_by_id(item.id)
        assert retrieved is not None
        assert retrieved.content == "test content"

    @pytest.mark.asyncio
    async def test_semantic_table_creation(
        self, semantic_adapter: LanceDBMemoryAdapter, embedding_service: EmbeddingService
    ):
        """Test semantic memory table is created and can store/retrieve data."""
        semantic = SemanticMemory(storage=semantic_adapter, limit=100)
        await semantic.initialize()

        # Verify initialization succeeded
        assert semantic._initialized is True

        # Verify we can store and retrieve data
        context = MemoryContext(
            agent_id="test_agent",
            session_id="test_session",
            conversation_id="test_conversation",
        )
        embedding = await embedding_service.embed_async("Python is a programming language")
        summary_embedding = await embedding_service.embed_async("Python definition")

        item = MemoryItem(
            id=str(uuid.uuid4()),
            content="Python is a programming language",
            summary="Python definition",
            context=context,
            importance=0.9,
            tier=MemoryTier.SEMANTIC,
            creator_agent_id=context.agent_id,
            modifier_agent_id=context.agent_id,
            subject="Python",
            relationship="is_a",
            object="programming language",
            confidence=0.95,
            embedding=embedding,
            summary_embedding=summary_embedding,
        )
        await semantic.store(item)

        # Verify retrieval works
        retrieved = await semantic.get_by_id(item.id)
        assert retrieved is not None
        assert retrieved.subject == "Python"

    @pytest.mark.asyncio
    async def test_table_persistence(
        self, db_manager: LanceDBManager, embedding_service: EmbeddingService
    ):
        """Test that tables persist across instances."""
        # Create adapter and first memory instance
        adapter = LanceDBMemoryAdapter(db_manager, table_name="memory_episodic_persistence")
        episodic1 = EpisodicMemory(storage=adapter, limit=100)
        await episodic1.initialize()

        # Store an item
        context = MemoryContext(
            agent_id="test_agent",
            session_id="test_session",
            conversation_id="test_conversation",
        )
        embedding = await embedding_service.embed_async("test content")
        summary_embedding = await embedding_service.embed_async("test summary")

        item = MemoryItem(
            id=str(uuid.uuid4()),
            content="test content",
            summary="test summary",
            context=context,
            importance=0.8,
            tier=MemoryTier.EPISODIC,
            creator_agent_id=context.agent_id,
            modifier_agent_id=context.agent_id,
            event_type="test",
            embedding=embedding,
            summary_embedding=summary_embedding,
        )
        await episodic1.store(item)

        # Create second instance with same adapter (shares table)
        episodic2 = EpisodicMemory(storage=adapter, limit=100)
        await episodic2.initialize()

        # Verify item persisted
        retrieved = await episodic2.get_by_id(item.id)
        assert retrieved is not None
        assert retrieved.content == "test content"


class TestLanceDBVectorSearch:
    """Test vector search operations."""

    @pytest.mark.asyncio
    async def test_episodic_vector_search(
        self, episodic_adapter: LanceDBMemoryAdapter, embedding_service: EmbeddingService, test_context: MemoryContext
    ):
        """Test vector similarity search in episodic memory."""
        episodic = EpisodicMemory(storage=episodic_adapter, limit=100)
        await episodic.initialize()

        # Store multiple items with different content
        contents = [
            "Python programming language",
            "JavaScript web development",
            "Machine learning algorithms",
        ]

        for content in contents:
            embedding = await embedding_service.embed_async(content)
            summary_embedding = await embedding_service.embed_async(content[:20])
            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=content,
                summary=content[:20],
                context=test_context,
                importance=0.7,
                tier=MemoryTier.EPISODIC,
                creator_agent_id=test_context.agent_id,
                modifier_agent_id=test_context.agent_id,
                event_type="test",
                embedding=embedding,
                summary_embedding=summary_embedding,
            )
            await episodic.store(item)

        # Search for Python-related content
        query_embedding = await embedding_service.embed_async("Python coding")
        results = await episodic.retrieve(
            query_embedding=query_embedding, context=test_context, limit=3
        )

        # Verify results
        assert len(results) > 0

        # Results are ordered by recency, so check similarity ranking separately
        most_relevant = max(results, key=lambda r: r.relevance_score)
        assert "Python" in most_relevant.item.content

    @pytest.mark.asyncio
    async def test_semantic_vector_search(
        self, semantic_adapter: LanceDBMemoryAdapter, embedding_service: EmbeddingService, test_context: MemoryContext
    ):
        """Test vector similarity search in semantic memory."""
        semantic = SemanticMemory(storage=semantic_adapter, limit=100)
        await semantic.initialize()

        # Store multiple facts
        facts = [
            ("Python", "is_a", "programming language"),
            ("JavaScript", "is_a", "programming language"),
            ("TensorFlow", "is_a", "machine learning framework"),
        ]

        for subject, relationship, obj in facts:
            content = f"{subject} {relationship} {obj}"
            embedding = await embedding_service.embed_async(content)
            summary_embedding = await embedding_service.embed_async(content[:20])
            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=content,
                summary=content[:20],
                context=test_context,
                importance=0.8,
                tier=MemoryTier.SEMANTIC,
                creator_agent_id=test_context.agent_id,
                modifier_agent_id=test_context.agent_id,
                subject=subject,
                relationship=relationship,
                object=obj,
                confidence=0.9,
                embedding=embedding,
                summary_embedding=summary_embedding,
            )
            await semantic.store(item)

        # Search for programming language facts
        query_embedding = await embedding_service.embed_async("programming language")
        results = await semantic.retrieve(
            query_embedding=query_embedding,
            context=test_context,
            limit=3,
        )

        # Verify results
        assert len(results) >= 2
        # Should find both Python and JavaScript
        contents = [r.item.content for r in results]
        assert any("Python" in c for c in contents)


class TestLanceDBConcurrentAccess:
    """Test concurrent access to LanceDB."""

    @pytest.mark.asyncio
    async def test_concurrent_writes(
        self, episodic_adapter: LanceDBMemoryAdapter, embedding_service: EmbeddingService, test_context: MemoryContext
    ):
        """Test concurrent write operations."""
        episodic = EpisodicMemory(storage=episodic_adapter, limit=100)
        await episodic.initialize()

        async def store_item(index: int):
            content = f"Test content {index}"
            embedding = await embedding_service.embed_async(content)
            summary_embedding = await embedding_service.embed_async(content[:10])
            item = MemoryItem(
                id=str(uuid.uuid4()),
                content=content,
                summary=content[:10],
                context=test_context,
                importance=0.7,
                tier=MemoryTier.EPISODIC,
                creator_agent_id=test_context.agent_id,
                modifier_agent_id=test_context.agent_id,
                event_type="test",
                embedding=embedding,
                summary_embedding=summary_embedding,
            )
            await episodic.store(item)
            return item.id

        # Store 10 items concurrently
        tasks = [store_item(i) for i in range(10)]
        item_ids = await asyncio.gather(*tasks)

        # Verify all items were stored
        assert len(item_ids) == 10
        assert len(set(item_ids)) == 10  # All unique

        # Verify all items can be retrieved
        for item_id in item_ids:
            item = await episodic.get_by_id(item_id)
            assert item is not None

    @pytest.mark.asyncio
    async def test_concurrent_reads(
        self, episodic_adapter: LanceDBMemoryAdapter, embedding_service: EmbeddingService, test_context: MemoryContext
    ):
        """Test concurrent read operations."""
        episodic = EpisodicMemory(storage=episodic_adapter, limit=100)
        await episodic.initialize()

        # Store a single item
        content = "Test content for concurrent reads"
        embedding = await embedding_service.embed_async(content)
        summary_embedding = await embedding_service.embed_async(content[:20])
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=content,
            summary=content[:20],
            context=test_context,
            importance=0.7,
            tier=MemoryTier.EPISODIC,
            creator_agent_id=test_context.agent_id,
            modifier_agent_id=test_context.agent_id,
            event_type="test",
            embedding=embedding,
            summary_embedding=summary_embedding,
        )
        await episodic.store(item)

        # Read concurrently
        async def read_item():
            return await episodic.get_by_id(item.id)

        tasks = [read_item() for _ in range(10)]
        results = await asyncio.gather(*tasks)

        # Verify all reads succeeded
        assert len(results) == 10
        assert all(r is not None for r in results)
        assert all(r.content == content for r in results)


class TestLanceDBDataPersistence:
    """Test data persistence across operations."""

    @pytest.mark.asyncio
    async def test_update_persistence(
        self, episodic_adapter: LanceDBMemoryAdapter, embedding_service: EmbeddingService, test_context: MemoryContext
    ):
        """Test that updates persist correctly."""
        episodic = EpisodicMemory(storage=episodic_adapter, limit=100)
        await episodic.initialize()

        # Store an item
        content = "Original content"
        embedding = await embedding_service.embed_async(content)
        summary_embedding = await embedding_service.embed_async(content[:10])
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=content,
            summary=content[:10],
            context=test_context,
            importance=0.7,
            tier=MemoryTier.EPISODIC,
            creator_agent_id=test_context.agent_id,
            modifier_agent_id=test_context.agent_id,
            event_type="test",
            embedding=embedding,
            summary_embedding=summary_embedding,
        )
        await episodic.store(item)

        # Update importance
        item.importance = 0.9
        await episodic.update(item)

        # Retrieve and verify
        retrieved = await episodic.get_by_id(item.id)
        assert retrieved.importance == 0.9

    @pytest.mark.asyncio
    async def test_delete_persistence(
        self, episodic_adapter: LanceDBMemoryAdapter, embedding_service: EmbeddingService, test_context: MemoryContext
    ):
        """Test that deletes persist correctly."""
        episodic = EpisodicMemory(storage=episodic_adapter, limit=100)
        await episodic.initialize()

        # Store an item
        content = "Content to delete"
        embedding = await embedding_service.embed_async(content)
        summary_embedding = await embedding_service.embed_async(content[:10])
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=content,
            summary=content[:10],
            context=test_context,
            importance=0.7,
            tier=MemoryTier.EPISODIC,
            creator_agent_id=test_context.agent_id,
            modifier_agent_id=test_context.agent_id,
            event_type="test",
            embedding=embedding,
            summary_embedding=summary_embedding,
        )
        await episodic.store(item)

        # Verify it exists
        assert await episodic.get_by_id(item.id) is not None

        # Delete it
        deleted = await episodic.delete(item.id)
        assert deleted is True

        # Verify it's gone
        assert await episodic.get_by_id(item.id) is None
