"""Tests for context builder service."""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from agentic_inquiry.database.results import SearchResult
from agentic_inquiry.mcp.services.context_builder import (
    ContextBuilder,
    ContextItem,
    TokenBudget,
)
from agentic_inquiry.mcp.services.token_optimizer import TokenOptimizer
from agentic_inquiry.mcp.models.session import Session, SessionState
from agentic_inquiry.memory.models import (
    MemoryItem,
    MemoryContext,
    MemoryTier,
    RetrievalResult,
)


@pytest.fixture
def mock_search_service():
    """Create mock search service."""
    service = AsyncMock()
    service.embedder = AsyncMock()
    service.embedder.embed_query = AsyncMock(return_value=[0.1] * 384)
    service.hybrid_search = AsyncMock(return_value=[])
    service.traverse_relationships = AsyncMock(
        return_value={
            "entity": {"id": "e1", "name": "TestEntity", "type": "function"},
            "relationships": [],
            "entities": {},
        }
    )
    return service


@pytest.fixture
def mock_memory_system():
    """Create mock memory system."""
    system = AsyncMock()
    system.retrieve = AsyncMock(return_value=[])
    return system


@pytest.fixture
def mock_db_manager():
    """Create mock database manager (as StorageFacade).

    ContextBuilder expects a StorageFacade with get_db_manager() method
    that returns a db manager with count_records method.
    """
    # Create the underlying db manager mock
    underlying_db = AsyncMock()
    underlying_db.count_records.return_value = 0

    # Create StorageFacade mock with get_db_manager()
    facade = MagicMock()
    facade.get_db_manager = MagicMock(return_value=underlying_db)

    return facade


@pytest.fixture
def mock_session_manager():
    """Create mock session manager."""
    manager = AsyncMock()

    # Create a test session
    test_session = Session(
        session_id="test-session-123",
        project_id="test-project",
        created_at=datetime.now(),
        last_active=datetime.now(),
        description="Test session",
        log_file="/tmp/test.log",
        state=SessionState.ACTIVE,
        status="active",
        context_state={},
        is_expired=False,
        history=[],
    )

    manager.get_session = AsyncMock(return_value=test_session)
    return manager


@pytest.fixture
def mock_config():
    """Create mock config."""
    config = MagicMock()
    # MCP query limits
    config.mcp.query.traversal_limit = 100
    config.mcp.query.tree_limit = 50
    return config


@pytest.fixture
def context_builder(
    mock_search_service,
    mock_memory_system,
    mock_db_manager,
    mock_session_manager,
    mock_config,
):
    """Create context builder instance."""
    return ContextBuilder(
        search_service=mock_search_service,
        memory_system=mock_memory_system,
        db_manager=mock_db_manager,
        session_manager=mock_session_manager,
        config=mock_config,
    )


class TestContextItem:
    """Tests for ContextItem dataclass."""

    def test_context_item_creation(self):
        """Test creating a context item."""
        item = ContextItem(
            id="test-id",
            type="code",
            name="test_function",
            summary="A test function",
            relevance_score=0.85,
            location="test.py:10",
            snippet="def test_function():",
            why_relevant="Matches query",
        )

        assert item.id == "test-id"
        assert item.type == "code"
        assert item.relevance_score == 0.85
        assert item.metadata == {}

    def test_context_item_with_metadata(self):
        """Test context item with metadata."""
        item = ContextItem(
            id="test-id",
            type="code",
            name="test_function",
            summary="A test function",
            relevance_score=0.85,
            location="test.py:10",
            snippet="def test_function():",
            metadata={"language": "python"},
            why_relevant="Matches query",
        )

        assert item.metadata["language"] == "python"


class TestContextBuilder:
    """Tests for ContextBuilder service."""

    @pytest.mark.asyncio
    async def test_build_context_empty_results(self, context_builder):
        """Test building context with no results."""
        result = await context_builder.build_context(
            query="test query",
            session_id="test-session-123",
            focus="all",
            depth="broad",
            max_tokens=4000,
        )

        assert "context" in result
        assert "summary" in result
        assert "suggestions" in result
        assert "token_usage" in result

        # Should have empty lists for each category
        assert result["context"]["code"] == []
        assert result["context"]["documentation"] == []
        assert result["context"]["memories"] == []
        assert result["context"]["relationships"] == []

        # Summary should indicate no results
        assert "No relevant context found" in result["summary"]

    @pytest.mark.asyncio
    async def test_build_context_with_code_results(
        self, context_builder, mock_search_service
    ):
        """Test building context with code results."""
        # Mock search results - must be SearchResult objects with .data attribute
        mock_search_service.hybrid_search.return_value = [
            SearchResult(
                id="code1",
                data={
                    "id": "code1",
                    "name": "test_function",
                    "type": "code",
                    "content": "def test_function(): pass",
                    "summary": "A test function",
                    "file_path": "test.py",
                    "language": "python",
                    "entity_type": "function",
                },
                score=0.8,
                source="hybrid",
                distance=0.2,
            )
        ]

        result = await context_builder.build_context(
            query="test function",
            session_id="test-session-123",
            focus="code",
            depth="focused",
            max_tokens=4000,
        )

        assert len(result["context"]["code"]) == 1
        assert result["context"]["code"][0]["name"] == "test_function"
        assert result["context"]["code"][0]["type"] == "code"
        assert result["token_usage"]["estimated_tokens"] > 0

    @pytest.mark.asyncio
    async def test_build_context_with_documentation_results(
        self, context_builder, mock_search_service
    ):
        """Test building context with documentation results."""
        # Mock search results - must be SearchResult objects
        mock_search_service.hybrid_search.return_value = [
            SearchResult(
                id="doc1",
                data={
                    "id": "doc1",
                    "name": "API Documentation",
                    "type": "documentation",
                    "content": "This is API documentation",
                    "summary": "API docs",
                    "file_path": "docs/api.md",
                },
                score=0.7,
                source="hybrid",
                distance=0.3,
            )
        ]

        result = await context_builder.build_context(
            query="API documentation",
            session_id="test-session-123",
            focus="docs",
            depth="focused",
            max_tokens=4000,
        )

        assert len(result["context"]["documentation"]) == 1
        assert result["context"]["documentation"][0]["name"] == "API Documentation"

    @pytest.mark.asyncio
    async def test_build_context_with_memories(
        self, context_builder, mock_memory_system
    ):
        """Test building context with memories."""
        # Create proper MemoryItem and RetrievalResult objects
        memory_context = MemoryContext(
            agent_id="test-agent",
            session_id="test-session-123",
            conversation_id="test-conversation",
            project_id="test-project",
        )

        memory_item = MemoryItem(
            id="mem1",
            content="We found that the API uses JWT tokens",
            summary="Previous finding",
            context=memory_context,
            importance=0.9,
            tier=MemoryTier.EPISODIC,
            creator_agent_id="test-agent",
            modifier_agent_id="test-agent",
            created_at=datetime(2024, 1, 1, 0, 0, 0),
        )

        retrieval_result = RetrievalResult(
            item=memory_item, relevance_score=0.9, retrieval_tier=MemoryTier.EPISODIC
        )

        # Mock memory results with proper RetrievalResult objects
        mock_memory_system.retrieve.return_value = [retrieval_result]

        result = await context_builder.build_context(
            query="authentication",
            session_id="test-session-123",
            focus="memories",
            depth="focused",
            max_tokens=4000,
        )

        assert len(result["context"]["memories"]) == 1
        assert result["context"]["memories"][0]["summary"] == "Previous finding"
        assert result["context"]["memories"][0]["type"] == "memory"

    @pytest.mark.asyncio
    async def test_build_context_token_budget_enforcement(
        self, context_builder, mock_search_service
    ):
        """Test that token budget is enforced."""
        # Mock many results - must be SearchResult objects
        mock_results = [
            SearchResult(
                id=f"code{i}",
                data={
                    "id": f"code{i}",
                    "name": f"function_{i}",
                    "type": "code",
                    "content": "def function(): pass" * 100,  # Large content
                    "summary": "A function" * 50,
                    "file_path": f"test{i}.py",
                },
                score=0.9,
                source="hybrid",
                distance=0.1,
            )
            for i in range(20)
        ]
        mock_search_service.hybrid_search.return_value = mock_results

        result = await context_builder.build_context(
            query="test",
            session_id="test-session-123",
            focus="code",
            depth="comprehensive",
            max_tokens=1000,  # Small budget
        )

        # Should have stopped adding items when budget was exceeded
        assert result["token_usage"]["estimated_tokens"] <= 1000
        assert len(result["context"]["code"]) < 20

    @pytest.mark.asyncio
    async def test_build_context_with_relationships(
        self, context_builder, mock_search_service
    ):
        """Test building context with relationship expansion."""
        # Mock code results - must be SearchResult objects
        mock_search_service.hybrid_search.return_value = [
            SearchResult(
                id="code1",
                data={
                    "id": "code1",
                    "name": "test_function",
                    "type": "code",
                    "content": "def test_function(): pass",
                    "summary": "A test function",
                    "file_path": "test.py",
                },
                score=0.8,
                source="hybrid",
                distance=0.2,
            )
        ]

        # Mock relationship traversal
        mock_search_service.traverse_relationships.return_value = {
            "entity": {"id": "code1", "name": "test_function", "type": "function"},
            "relationships": [
                {
                    "id": "rel1",
                    "source_id": "code1",
                    "target_id": "code2",
                    "type": "calls",
                    "direction": "outgoing",
                    "depth": 1,
                    "target_name": "helper_function",
                    "target_type": "function",
                }
            ],
            "entities": {
                "code2": {
                    "id": "code2",
                    "name": "helper_function",
                    "type": "function",
                    "file_path": "helpers.py",
                    "summary": "A helper function",
                }
            },
        }

        result = await context_builder.build_context(
            query="test function",
            session_id="test-session-123",
            focus="code",
            depth="broad",  # Enables relationship expansion
            max_tokens=4000,
        )

        # Should have relationships
        assert len(result["context"]["relationships"]) > 0
        assert result["context"]["relationships"][0]["relationship_type"] == "calls"

    @pytest.mark.asyncio
    async def test_build_context_focused_depth_no_relationships(
        self, context_builder, mock_search_service
    ):
        """Test that focused depth doesn't expand relationships."""
        # Mock code results - must be SearchResult objects
        mock_search_service.hybrid_search.return_value = [
            SearchResult(
                id="code1",
                data={
                    "id": "code1",
                    "name": "test_function",
                    "type": "code",
                    "content": "def test_function(): pass",
                    "summary": "A test function",
                    "file_path": "test.py",
                },
                score=0.8,
                source="hybrid",
                distance=0.2,
            )
        ]

        result = await context_builder.build_context(
            query="test function",
            session_id="test-session-123",
            focus="code",
            depth="focused",  # Should not expand relationships
            max_tokens=4000,
        )

        # Should have no relationships
        assert len(result["context"]["relationships"]) == 0

    @pytest.mark.asyncio
    async def test_build_context_invalid_session(
        self, context_builder, mock_session_manager
    ):
        """Test building context with invalid session."""
        mock_session_manager.get_session.return_value = None

        with pytest.raises(ValueError, match="Session .* not found"):
            await context_builder.build_context(
                query="test",
                session_id="invalid-session",
                focus="all",
                depth="broad",
                max_tokens=4000,
            )

    @pytest.mark.asyncio
    async def test_build_context_overview(self, context_builder, mock_search_service):
        """Test building context overview for progressive discovery."""
        # Mock search results - must be SearchResult objects
        mock_search_service.hybrid_search.return_value = [
            SearchResult(
                id=f"code{i}",
                data={
                    "id": f"code{i}",
                    "name": f"function_{i}",
                    "type": "code",
                    "file_path": f"test{i}.py",
                },
                score=0.9 - (i * 0.01),
                source="hybrid",
                distance=0.1 + (i * 0.01),
            )
            for i in range(10)
        ]

        result = await context_builder.build_context_overview(
            query="test", session_id="test-session-123", max_tokens=2000
        )

        assert "categories" in result
        assert "code" in result["categories"]
        assert "documentation" in result["categories"]
        assert "memories" in result["categories"]

        # Should have counts
        assert result["categories"]["code"]["total_count"] == 10
        assert len(result["categories"]["code"]["top_items"]) <= 3

        # Should have suggestions
        assert len(result["suggestions"]) > 0

    @pytest.mark.asyncio
    async def test_expand_category(self, context_builder, mock_search_service):
        """Test expanding a specific category."""
        # Mock search results - must be SearchResult objects
        mock_search_service.hybrid_search.return_value = [
            SearchResult(
                id=f"code{i}",
                data={
                    "id": f"code{i}",
                    "name": f"function_{i}",
                    "type": "code",
                    "content": "def function(): pass",
                    "summary": "A function",
                    "file_path": f"test{i}.py",
                },
                score=0.9,
                source="hybrid",
                distance=0.1,
            )
            for i in range(5)
        ]

        result = await context_builder.expand_category(
            query="test",
            session_id="test-session-123",
            category="code",
            max_tokens=3000,
        )

        assert "items" in result
        assert "category" in result
        assert result["category"] == "code"
        assert len(result["items"]) == 5

        # Should track exploration in session state
        # (This would be verified by checking session state in a real test)

    @pytest.mark.asyncio
    async def test_get_relationship_preview(self, context_builder, mock_search_service):
        """Test getting relationship preview."""
        # Mock relationship traversal
        mock_search_service.traverse_relationships.return_value = {
            "entity": {"id": "e1", "name": "TestFunction", "type": "function"},
            "relationships": [
                {
                    "id": "rel1",
                    "source_id": "e1",
                    "target_id": "e2",
                    "type": "calls",
                    "direction": "outgoing",
                    "target_name": "helper1",
                },
                {
                    "id": "rel2",
                    "source_id": "e1",
                    "target_id": "e3",
                    "type": "calls",
                    "direction": "outgoing",
                    "target_name": "helper2",
                },
                {
                    "id": "rel3",
                    "source_id": "e4",
                    "target_id": "e1",
                    "type": "calls",
                    "direction": "incoming",
                    "source_name": "caller1",
                },
            ],
            "entities": {},
        }

        result = await context_builder.get_relationship_preview(
            entity_id="e1", session_id="test-session-123", max_depth=1
        )

        assert "entity" in result
        assert result["entity"]["id"] == "e1"
        assert "relationship_summary" in result
        assert result["total_relationships"] == 3

        # Should have summary by type and direction
        summary = result["relationship_summary"]
        assert len(summary) == 2  # calls_outgoing and calls_incoming

        # Find the outgoing calls summary
        outgoing = next(s for s in summary if s["direction"] == "outgoing")
        assert outgoing["count"] == 2
        assert len(outgoing["example_targets"]) == 2


class TestTokenBudget:
    """Tests for TokenBudget utility."""

    def test_token_budget_creation(self):
        """Test creating a token budget."""
        budget = TokenBudget(max_tokens=1000)
        assert budget.max_tokens == 1000
        assert budget.used_tokens == 0
        assert budget.remaining() == 1000

    def test_token_budget_add(self):
        """Test adding text to budget."""
        budget = TokenBudget(max_tokens=1000)

        # Add text that fits
        assert budget.add("Hello world")
        assert budget.used_tokens > 0

        # Try to add text that exceeds budget
        large_text = "word " * 1000
        assert not budget.add(large_text)

    def test_token_budget_can_add(self):
        """Test checking if text can be added."""
        budget = TokenBudget(max_tokens=100)

        small_text = "Hello"
        assert budget.can_add(small_text)

        large_text = "word " * 1000
        assert not budget.can_add(large_text)

    def test_token_budget_usage_percentage(self):
        """Test calculating usage percentage."""
        budget = TokenBudget(max_tokens=1000)
        budget.used_tokens = 500

        assert budget.usage_percentage() == 50.0

    def test_token_budget_reset(self):
        """Test resetting budget."""
        budget = TokenBudget(max_tokens=1000)
        budget.add("Hello world")

        assert budget.used_tokens > 0

        budget.reset()
        assert budget.used_tokens == 0


class TestTokenOptimizer:
    """Tests for TokenOptimizer utility."""

    def test_create_snippet(self):
        """Test creating a snippet."""
        optimizer = TokenOptimizer()

        long_text = "This is a very long text. " * 100
        snippet = optimizer.create_snippet(long_text, max_tokens=50)

        # Should be truncated
        assert len(snippet) < len(long_text)
        assert snippet.endswith("...")

    def test_create_snippet_short_text(self):
        """Test creating snippet from short text."""
        optimizer = TokenOptimizer()

        short_text = "Short text"
        snippet = optimizer.create_snippet(short_text, max_tokens=50)

        # Should not be truncated
        assert snippet == short_text
        assert not snippet.endswith("...")

    def test_truncate_to_tokens(self):
        """Test truncating text to token limit."""
        optimizer = TokenOptimizer()

        long_text = "word " * 1000
        truncated = optimizer.truncate_to_tokens(long_text, max_tokens=50)

        # Should be shorter
        assert len(truncated) < len(long_text)

    def test_estimate_tokens(self):
        """Test estimating token count."""
        optimizer = TokenOptimizer()

        text = "Hello world, this is a test"
        tokens = optimizer.estimate_tokens(text)

        # Should return a reasonable estimate
        assert tokens > 0
        assert tokens < len(text)  # Should be less than character count
