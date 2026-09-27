# tests/mcp/services/test_gatherers.py
"""Tests for context gatherer implementations."""
import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock

from agentic_inquiry.mcp.services.gatherers import (
    ContextGathererProtocol,
    GatherContext,
    CodeGatherer,
    DocsGatherer,
    MemoryGatherer,
    GraphGatherer,
)
from agentic_inquiry.database.results import SearchResult
from agentic_inquiry.mcp.services.token_optimizer import TokenBudget, TokenOptimizer
from agentic_inquiry.memory.models import MemoryContext, MemoryItem, MemoryTier, RetrievalResult


def _search_result(data):
    """A hybrid-search hit carrying data, as SearchService returns it."""
    return SearchResult(id=data["id"], data=data, score=0.8)


class TestGatherContext:
    """Tests for GatherContext dataclass."""

    def test_gather_context_creation(self):
        """Test basic GatherContext creation."""
        budget = TokenBudget(max_tokens=1000)
        context = GatherContext(
            query="test query",
            budget=budget,
            depth="broad",
            project_id="test_project",
            session_id="test_session",
        )

        assert context.query == "test query"
        assert context.budget == budget
        assert context.depth == "broad"
        assert context.project_id == "test_project"
        assert context.session_id == "test_session"
        assert context.include_overview is False
        assert context.query_vector is None
        assert context.initial_context == {}

    def test_gather_context_with_query_vector(self):
        """Test GatherContext with pre-computed query vector."""
        budget = TokenBudget(max_tokens=1000)
        query_vector = [0.1, 0.2, 0.3]
        context = GatherContext(
            query="test query",
            budget=budget,
            depth="comprehensive",
            project_id="test_project",
            session_id="test_session",
            query_vector=query_vector,
        )

        assert context.query_vector == query_vector

    def test_gather_context_with_initial_context(self):
        """Test GatherContext with initial context for graph expansion."""
        budget = TokenBudget(max_tokens=1000)
        initial_context = {
            "code": [{"id": "chunk_1"}],
            "documentation": [{"id": "doc_1"}],
        }
        context = GatherContext(
            query="test query",
            budget=budget,
            depth="comprehensive",
            project_id="test_project",
            session_id="test_session",
            initial_context=initial_context,
        )

        assert context.initial_context == initial_context


class TestCodeGatherer:
    """Tests for CodeGatherer."""

    @pytest.fixture
    def mock_search_service(self):
        """Create a mock search service."""
        search_service = MagicMock()
        search_service.embedding_service = MagicMock()
        search_service.embedding_service.embed_async = AsyncMock(
            return_value=MagicMock(tolist=lambda: [0.1, 0.2, 0.3])
        )
        search_service.hybrid_search = AsyncMock(return_value=[])
        return search_service

    @pytest.fixture
    def mock_token_optimizer(self):
        """Create a mock token optimizer."""
        optimizer = MagicMock(spec=TokenOptimizer)
        optimizer.create_snippet = MagicMock(return_value="snippet text")
        return optimizer

    @pytest.fixture
    def code_gatherer(self, mock_search_service, mock_token_optimizer):
        """Create a CodeGatherer instance."""
        return CodeGatherer(mock_search_service, mock_token_optimizer)

    def test_gatherer_type(self, code_gatherer):
        """Test gatherer_type property."""
        assert code_gatherer.gatherer_type == "code"

    def test_implements_protocol(self, code_gatherer):
        """Test that CodeGatherer implements ContextGathererProtocol."""
        assert isinstance(code_gatherer, ContextGathererProtocol)

    @pytest.mark.asyncio
    async def test_gather_without_project_id(self, code_gatherer):
        """Test gather returns empty list without project_id."""
        budget = TokenBudget(max_tokens=1000)
        context = GatherContext(
            query="test query",
            budget=budget,
            depth="broad",
            project_id=None,  # No project_id
            session_id="test_session",
        )

        result = await code_gatherer.gather(context)
        assert result == []

    @pytest.mark.asyncio
    async def test_gather_with_empty_results(
        self, code_gatherer, mock_search_service
    ):
        """Test gather with empty search results."""
        mock_search_service.hybrid_search.return_value = []

        budget = TokenBudget(max_tokens=1000)
        context = GatherContext(
            query="test query",
            budget=budget,
            depth="broad",
            project_id="test_project",
            session_id="test_session",
        )

        result = await code_gatherer.gather(context)
        assert result == []

    @pytest.mark.asyncio
    async def test_gather_with_code_results(
        self, code_gatherer, mock_search_service
    ):
        """Test gather with code search results."""
        # Create mock search results
        mock_result = _search_result({
            "id": "chunk_1",
            "file_path": "src/test.py",
            "name": "test_function",
            "summary": "A test function",
            "content": "def test_function(): pass",
            "_distance": 0.2,
            "language": "python",
        })
        mock_search_service.hybrid_search.return_value = [mock_result]

        budget = TokenBudget(max_tokens=1000)
        context = GatherContext(
            query="test query",
            budget=budget,
            depth="broad",
            project_id="test_project",
            session_id="test_session",
        )

        result = await code_gatherer.gather(context)

        assert len(result) == 1
        assert result[0]["id"] == "chunk_1"
        assert result[0]["type"] == "code"
        assert result[0]["name"] == "test_function"

    @pytest.mark.asyncio
    async def test_gather_filters_non_code_files(
        self, code_gatherer, mock_search_service
    ):
        """Test that gather filters out non-code files."""
        # Create mock results with both code and non-code files
        code_result = _search_result({
            "id": "code_1",
            "file_path": "src/test.py",
            "name": "test_function",
            "summary": "A test function",
            "content": "def test_function(): pass",
            "_distance": 0.2,
        })

        doc_result = _search_result({
            "id": "doc_1",
            "file_path": "docs/readme.md",
            "name": "readme",
            "summary": "Documentation",
            "content": "# Readme",
            "_distance": 0.3,
        })

        mock_search_service.hybrid_search.return_value = [code_result, doc_result]

        budget = TokenBudget(max_tokens=1000)
        context = GatherContext(
            query="test query",
            budget=budget,
            depth="broad",
            project_id="test_project",
            session_id="test_session",
        )

        result = await code_gatherer.gather(context)

        # Should only return the code file
        assert len(result) == 1
        assert result[0]["id"] == "code_1"

    @pytest.mark.asyncio
    async def test_gather_respects_token_budget(
        self, code_gatherer, mock_search_service, mock_token_optimizer
    ):
        """Test that gather respects token budget."""
        # Create many mock results
        results = []
        for i in range(20):
            mock_result = _search_result({
                "id": f"chunk_{i}",
                "file_path": f"src/test_{i}.py",
                "name": f"function_{i}",
                "summary": f"Function {i}",
                "content": f"def function_{i}(): pass",
                "_distance": 0.2,
            })
            results.append(mock_result)

        mock_search_service.hybrid_search.return_value = results

        # Very small budget
        budget = TokenBudget(max_tokens=100)
        context = GatherContext(
            query="test query",
            budget=budget,
            depth="broad",
            project_id="test_project",
            session_id="test_session",
        )

        result = await code_gatherer.gather(context)

        # Should stop before processing all results due to budget
        assert 0 < len(result) < len(results)


class TestDocsGatherer:
    """Tests for DocsGatherer."""

    @pytest.fixture
    def mock_search_service(self):
        """Create a mock search service."""
        search_service = MagicMock()
        search_service.embedding_service = MagicMock()
        search_service.embedding_service.embed_async = AsyncMock(
            return_value=MagicMock(tolist=lambda: [0.1, 0.2, 0.3])
        )
        search_service.hybrid_search = AsyncMock(return_value=[])
        return search_service

    @pytest.fixture
    def mock_token_optimizer(self):
        """Create a mock token optimizer."""
        optimizer = MagicMock(spec=TokenOptimizer)
        optimizer.create_snippet = MagicMock(return_value="snippet text")
        return optimizer

    @pytest.fixture
    def docs_gatherer(self, mock_search_service, mock_token_optimizer):
        """Create a DocsGatherer instance."""
        return DocsGatherer(mock_search_service, mock_token_optimizer)

    def test_gatherer_type(self, docs_gatherer):
        """Test gatherer_type property."""
        assert docs_gatherer.gatherer_type == "documentation"

    def test_implements_protocol(self, docs_gatherer):
        """Test that DocsGatherer implements ContextGathererProtocol."""
        assert isinstance(docs_gatherer, ContextGathererProtocol)

    @pytest.mark.asyncio
    async def test_gather_filters_code_files(
        self, docs_gatherer, mock_search_service
    ):
        """Test that gather filters out code files."""
        # Create mock results with both doc and code files
        doc_result = _search_result({
            "id": "doc_1",
            "file_path": "docs/readme.md",
            "name": "readme",
            "summary": "Documentation",
            "content": "# Readme",
            "_distance": 0.2,
        })

        code_result = _search_result({
            "id": "code_1",
            "file_path": "src/test.py",
            "name": "test_function",
            "summary": "A test function",
            "content": "def test_function(): pass",
            "_distance": 0.3,
        })

        mock_search_service.hybrid_search.return_value = [doc_result, code_result]

        budget = TokenBudget(max_tokens=1000)
        context = GatherContext(
            query="test query",
            budget=budget,
            depth="broad",
            project_id="test_project",
            session_id="test_session",
        )

        result = await docs_gatherer.gather(context)

        # Should only return the doc file
        assert len(result) == 1
        assert result[0]["id"] == "doc_1"


class TestMemoryGatherer:
    """Tests for MemoryGatherer."""

    @pytest.fixture
    def mock_memory_system(self):
        """Create a mock memory system."""
        memory_system = MagicMock()
        memory_system.retrieve = AsyncMock(return_value=[])
        return memory_system

    @pytest.fixture
    def mock_token_optimizer(self):
        """Create a mock token optimizer."""
        optimizer = MagicMock(spec=TokenOptimizer)
        optimizer.create_snippet = MagicMock(return_value="snippet text")
        return optimizer

    @pytest.fixture
    def memory_gatherer(self, mock_memory_system, mock_token_optimizer):
        """Create a MemoryGatherer instance."""
        return MemoryGatherer(mock_memory_system, mock_token_optimizer)

    def test_gatherer_type(self, memory_gatherer):
        """Test gatherer_type property."""
        assert memory_gatherer.gatherer_type == "memories"

    def test_implements_protocol(self, memory_gatherer):
        """Test that MemoryGatherer implements ContextGathererProtocol."""
        assert isinstance(memory_gatherer, ContextGathererProtocol)

    @pytest.mark.asyncio
    async def test_gather_without_session_id(self, memory_gatherer):
        """Test gather returns empty list without session_id."""
        budget = TokenBudget(max_tokens=1000)
        context = GatherContext(
            query="test query",
            budget=budget,
            depth="broad",
            project_id="test_project",
            session_id=None,  # No session_id
        )

        result = await memory_gatherer.gather(context)
        assert result == []

    @pytest.mark.asyncio
    async def test_gather_with_memories(
        self, memory_gatherer, mock_memory_system
    ):
        """Test gather with memory results."""
        # Create mock memory result
        memory_item = MemoryItem(
            id="memory_1",
            content="The user mentioned they prefer Python for data analysis.",
            summary="User prefers Python",
            context=MemoryContext(
                agent_id="agent", session_id="test_session", conversation_id="conversation"
            ),
            importance=0.8,
            tier=MemoryTier.SEMANTIC,
            creator_agent_id="agent",
            modifier_agent_id="agent",
            metadata={"tags": ["preference"]},
        )
        mock_result = RetrievalResult(
            item=memory_item,
            relevance_score=0.85,
            retrieval_tier=MemoryTier.SEMANTIC,
        )

        mock_memory_system.retrieve.return_value = [mock_result]

        budget = TokenBudget(max_tokens=1000)
        context = GatherContext(
            query="programming preferences",
            budget=budget,
            depth="broad",
            project_id="test_project",
            session_id="test_session",
        )

        result = await memory_gatherer.gather(context)

        assert len(result) == 1
        assert result[0]["id"] == "memory_1"
        assert result[0]["type"] == "memory"


class TestGraphGatherer:
    """Tests for GraphGatherer."""

    @pytest.fixture
    def mock_search_service(self):
        """Create a mock search service."""
        search_service = MagicMock()
        search_service.traverse_relationships = AsyncMock(return_value={
            "relationships": [],
            "entities": {},
            "entity": {"name": ""}
        })
        return search_service

    @pytest.fixture
    def graph_gatherer(self, mock_search_service):
        """Create a GraphGatherer instance."""
        return GraphGatherer(mock_search_service)

    def test_gatherer_type(self, graph_gatherer):
        """Test gatherer_type property."""
        assert graph_gatherer.gatherer_type == "relationships"

    def test_implements_protocol(self, graph_gatherer):
        """Test that GraphGatherer implements ContextGathererProtocol."""
        assert isinstance(graph_gatherer, ContextGathererProtocol)

    @pytest.mark.asyncio
    async def test_gather_focused_depth_returns_empty(self, graph_gatherer):
        """Test that focused depth returns empty list."""
        budget = TokenBudget(max_tokens=1000)
        context = GatherContext(
            query="test query",
            budget=budget,
            depth="focused",  # No expansion for focused
            project_id="test_project",
            session_id="test_session",
        )

        result = await graph_gatherer.gather(context)
        assert result == []

    @pytest.mark.asyncio
    async def test_gather_without_project_id(self, graph_gatherer):
        """Test gather returns empty list without project_id."""
        budget = TokenBudget(max_tokens=1000)
        context = GatherContext(
            query="test query",
            budget=budget,
            depth="broad",
            project_id=None,  # No project_id
            session_id="test_session",
        )

        result = await graph_gatherer.gather(context)
        assert result == []

    @pytest.mark.asyncio
    async def test_gather_without_initial_context(self, graph_gatherer):
        """Test gather returns empty list without initial context."""
        budget = TokenBudget(max_tokens=1000)
        context = GatherContext(
            query="test query",
            budget=budget,
            depth="broad",
            project_id="test_project",
            session_id="test_session",
            initial_context={},  # Empty initial context
        )

        result = await graph_gatherer.gather(context)
        assert result == []

    @pytest.mark.asyncio
    async def test_gather_with_relationships(
        self, graph_gatherer, mock_search_service
    ):
        """Test gather with relationship results."""
        # Create mock relationship response
        mock_search_service.traverse_relationships.return_value = {
            "entity": {"name": "test_function"},
            "relationships": [
                {
                    "source_id": "entity_1",
                    "target_id": "entity_2",
                    "type": "calls",
                    "direction": "outgoing",
                    "depth": 1,
                    "metadata": {},
                }
            ],
            "entities": {
                "entity_2": {
                    "name": "helper_function",
                    "type": "function",
                    "file_path": "src/helpers.py",
                    "summary": "A helper function",
                }
            }
        }

        budget = TokenBudget(max_tokens=1000)
        context = GatherContext(
            query="test query",
            budget=budget,
            depth="broad",
            project_id="test_project",
            session_id="test_session",
            initial_context={
                "code": [{"id": "entity_1"}],
            },
        )

        result = await graph_gatherer.gather(context)

        assert len(result) == 1
        assert result[0]["id"] == "entity_2"
        assert result[0]["type"] == "relationship"
        assert result[0]["relationship_type"] == "calls"
