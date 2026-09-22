"""Tests for search with special characters in queries.

This module tests that queries containing special characters like
question marks, asterisks, brackets, etc. work correctly without
causing FTS syntax errors.
"""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock

from agentic_inquiry.config import Config
from agentic_inquiry.database.adapters.lancedb_adapter import LanceDBAdapter
from agentic_inquiry.database.results import SearchResult
from agentic_inquiry.search.service import SearchService


def _make_search_results(dicts: list, source: str = "test") -> list[SearchResult]:
    """Helper to create SearchResult objects from dict test data."""
    results = []
    for d in dicts:
        result_id = d.get("id") or d.get("doc_id") or d.get("chunk_id") or str(hash(str(d)))
        results.append(SearchResult(
            id=str(result_id),
            data=d,
            score=d.get("score", 0.5),
            source=source,
            distance=d.get("_distance"),
        ))
    return results


@pytest.fixture
def base_config():
    """Create a base configuration for testing."""
    config = Config.load()
    config.search.default_limit = 10
    config.search.query_sanitization.enabled = True
    config.search.query_sanitization.preserve_wildcards = False
    return config


@pytest.fixture
def mock_db_manager():
    """Create a mock database adapter."""
    mock_adapter = MagicMock(spec=LanceDBAdapter)
    mock_adapter.fts_search = AsyncMock()
    mock_adapter.vector_search = AsyncMock()
    mock_adapter.hybrid_search = AsyncMock()
    mock_adapter._manager = MagicMock()
    return mock_adapter


@pytest.fixture
def mock_storage_facade(mock_db_manager):
    """Create a mock StorageFacade.

    The mock needs async methods for search operations since SearchService
    now delegates to StorageFacade methods directly.
    """
    mock_storage = MagicMock()
    mock_storage.vector_provider = mock_db_manager
    mock_storage.project_id = "test_project"

    # Add async mock methods that SearchService.fts_search/vector_search delegate to
    mock_storage.fts_search = mock_db_manager.fts_search
    mock_storage.vector_search = mock_db_manager.vector_search
    mock_storage.hybrid_search = mock_db_manager.hybrid_search

    # Ensure get_backend_type returns "lancedb" so SearchService uses LanceDBAdapter
    mock_storage.get_backend_type = MagicMock(return_value="lancedb")

    return mock_storage


@pytest.fixture
def mock_event_system():
    """Create a mock event system."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


@pytest.fixture
def search_service(base_config, mock_storage_facade, mock_event_system):
    """Create a search service with mocked dependencies."""
    service = SearchService(
        storage=mock_storage_facade,
        config=base_config,
        event_system=mock_event_system,
    )
    return service


class TestSpecialCharacterSearch:
    """Test search with special characters in queries."""
    
    @pytest.mark.asyncio
    async def test_search_with_question_mark(self, search_service, mock_db_manager):
        """Test that queries with question marks work without syntax errors."""
        # Setup mock results
        mock_dicts = [
            {"id": "1", "content": "How does this work?", "doc_id": "doc1"},
            {"id": "2", "content": "What is the answer?", "doc_id": "doc2"},
        ]
        mock_db_manager.fts_search.return_value = _make_search_results(mock_dicts, source="fts")

        # Execute search with question mark
        query = "How does this work?"
        results = await search_service.fts_search(
            query_fts=query,
            limit=10
        )

        # Verify search was called with sanitized query
        mock_db_manager.fts_search.assert_called_once()
        call_args = mock_db_manager.fts_search.call_args
        sanitized_query = call_args.kwargs['query']

        # Verify question mark was escaped
        assert "\\?" in sanitized_query

        # Verify results were returned
        assert len(results) == 2
        assert results[0].data["content"] == "How does this work?"
    
    @pytest.mark.asyncio
    async def test_search_with_asterisk(self, search_service, mock_db_manager):
        """Test that queries with asterisks work without syntax errors."""
        # Setup mock results
        mock_results = [
            {"id": "1", "content": "file*.py pattern", "doc_id": "doc1"},
        ]
        mock_db_manager.fts_search.return_value = _make_search_results(mock_results, source="fts")
        
        # Execute search with asterisk
        query = "file*.py"
        results = await search_service.fts_search(
            query_fts=query,
            limit=10
        )
        
        # Verify search was called with sanitized query
        mock_db_manager.fts_search.assert_called_once()
        call_args = mock_db_manager.fts_search.call_args
        sanitized_query = call_args.kwargs['query']
        
        # Verify asterisk was escaped
        assert "\\*" in sanitized_query
        
        # Verify results were returned
        assert len(results) == 1
    
    @pytest.mark.asyncio
    async def test_search_with_brackets(self, search_service, mock_db_manager):
        """Test that queries with brackets work without syntax errors."""
        # Setup mock results
        mock_results = [
            {"id": "1", "content": "array[index] access", "doc_id": "doc1"},
        ]
        mock_db_manager.fts_search.return_value = _make_search_results(mock_results, source="fts")
        
        # Execute search with brackets
        query = "array[index]"
        results = await search_service.fts_search(
            query_fts=query,
            limit=10
        )
        
        # Verify search was called with sanitized query
        mock_db_manager.fts_search.assert_called_once()
        call_args = mock_db_manager.fts_search.call_args
        sanitized_query = call_args.kwargs['query']
        
        # Verify brackets were escaped
        assert "\\[" in sanitized_query
        assert "\\]" in sanitized_query
        
        # Verify results were returned
        assert len(results) == 1
    
    @pytest.mark.asyncio
    async def test_search_with_parentheses(self, search_service, mock_db_manager):
        """Test that queries with parentheses work without syntax errors."""
        # Setup mock results
        mock_results = [
            {"id": "1", "content": "function(args) call", "doc_id": "doc1"},
        ]
        mock_db_manager.fts_search.return_value = _make_search_results(mock_results, source="fts")
        
        # Execute search with parentheses
        query = "function(args)"
        results = await search_service.fts_search(
            query_fts=query,
            limit=10
        )
        
        # Verify search was called with sanitized query
        mock_db_manager.fts_search.assert_called_once()
        call_args = mock_db_manager.fts_search.call_args
        sanitized_query = call_args.kwargs['query']
        
        # Verify parentheses were escaped
        assert "\\(" in sanitized_query
        assert "\\)" in sanitized_query
        
        # Verify results were returned
        assert len(results) == 1
    
    @pytest.mark.asyncio
    async def test_search_with_multiple_special_chars(self, search_service, mock_db_manager):
        """Test that queries with multiple special characters work."""
        # Setup mock results
        mock_results = [
            {"id": "1", "content": "complex query", "doc_id": "doc1"},
        ]
        mock_db_manager.fts_search.return_value = _make_search_results(mock_results, source="fts")
        
        # Execute search with multiple special characters
        query = "What is array[0]?"
        results = await search_service.fts_search(
            query_fts=query,
            limit=10
        )
        
        # Verify search was called with sanitized query
        mock_db_manager.fts_search.assert_called_once()
        call_args = mock_db_manager.fts_search.call_args
        sanitized_query = call_args.kwargs['query']
        
        # Verify all special characters were escaped
        assert "\\?" in sanitized_query
        assert "\\[" in sanitized_query
        assert "\\]" in sanitized_query
        
        # Verify results were returned
        assert len(results) == 1
    
    @pytest.mark.asyncio
    async def test_hybrid_search_with_special_chars(self, search_service, mock_db_manager):
        """Test that hybrid search sanitizes FTS query but not vector query."""
        # Setup mock results as SearchResult objects (what vector_search/fts_search return)
        vector_dicts = [
            {"id": "v1", "content": "vector result", "doc_id": "doc1", "score": 0.9},
        ]
        fts_dicts = [
            {"id": "f1", "content": "fts result", "doc_id": "doc2", "score": 0.8},
        ]

        # Mock the individual search methods to return SearchResult objects
        search_service.vector_search = AsyncMock(
            return_value=_make_search_results(vector_dicts, source="vector")
        )
        search_service.fts_search = AsyncMock(
            return_value=_make_search_results(fts_dicts, source="fts")
        )

        # Mock reranker to return None (will use simple merge)
        search_service._create_reranker = MagicMock(return_value=None)

        # Execute hybrid search with special characters
        query_vector = [0.1] * 384
        query_fts = "How does this work?"
        results = await search_service.hybrid_search(
            query_vector=query_vector,
            query_fts=query_fts,
            limit=10
        )

        # Verify both searches were called
        search_service.vector_search.assert_called_once()
        search_service.fts_search.assert_called_once()

        # Verify FTS search received the query (it will sanitize internally)
        fts_call_args = search_service.fts_search.call_args
        assert fts_call_args.kwargs['query_fts'] == query_fts

        # Verify results were returned
        assert len(results) > 0
    
    @pytest.mark.asyncio
    async def test_sanitization_can_be_disabled(self, base_config, mock_storage_facade, mock_event_system):
        """Test that query sanitization can be disabled via configuration."""
        # Disable sanitization
        base_config.search.query_sanitization.enabled = False

        # Create service with sanitization disabled
        service = SearchService(
            storage=mock_storage_facade,
            config=base_config,
            event_system=mock_event_system,
        )

        # Get the mock_db_manager from the facade for assertions
        mock_db_manager = mock_storage_facade.vector_provider
        
        # Setup mock results
        mock_results = [
            {"id": "1", "content": "result", "doc_id": "doc1"},
        ]
        mock_db_manager.fts_search.return_value = _make_search_results(mock_results, source="fts")
        
        # Execute search with special characters
        query = "How does this work?"
        _results = await service.fts_search(
            query_fts=query,
            limit=10
        )
        
        # Verify search was called with original query (not sanitized)
        mock_db_manager.fts_search.assert_called_once()
        call_args = mock_db_manager.fts_search.call_args
        actual_query = call_args.kwargs['query']
        
        # Verify question mark was NOT escaped
        assert "\\?" not in actual_query
        assert actual_query == query
    
    @pytest.mark.asyncio
    async def test_empty_query_handling(self, search_service, mock_db_manager):
        """Test that empty queries are handled gracefully."""
        # Setup mock results
        mock_results = []
        mock_db_manager.fts_search.return_value = _make_search_results(mock_results, source="fts")
        
        # Execute search with empty query
        query = ""
        results = await search_service.fts_search(
            query_fts=query,
            limit=10
        )
        
        # Verify search was called
        mock_db_manager.fts_search.assert_called_once()
        
        # Verify empty results
        assert len(results) == 0
    
    @pytest.mark.asyncio
    async def test_query_with_backslash(self, search_service, mock_db_manager):
        """Test that queries with backslashes work correctly."""
        # Setup mock results
        mock_results = [
            {"id": "1", "content": "path\\to\\file", "doc_id": "doc1"},
        ]
        mock_db_manager.fts_search.return_value = _make_search_results(mock_results, source="fts")
        
        # Execute search with backslash
        query = "path\\to\\file"
        results = await search_service.fts_search(
            query_fts=query,
            limit=10
        )
        
        # Verify search was called with sanitized query
        mock_db_manager.fts_search.assert_called_once()
        call_args = mock_db_manager.fts_search.call_args
        sanitized_query = call_args.kwargs['query']
        
        # Verify backslashes were escaped
        assert "\\\\" in sanitized_query
        
        # Verify results were returned
        assert len(results) == 1
    
    @pytest.mark.asyncio
    async def test_query_with_plus_sign(self, search_service, mock_db_manager):
        """Test that queries with plus signs work correctly."""
        # Setup mock results
        mock_results = [
            {"id": "1", "content": "C++ programming", "doc_id": "doc1"},
        ]
        mock_db_manager.fts_search.return_value = _make_search_results(mock_results, source="fts")
        
        # Execute search with plus sign
        query = "C++"
        results = await search_service.fts_search(
            query_fts=query,
            limit=10
        )
        
        # Verify search was called with sanitized query
        mock_db_manager.fts_search.assert_called_once()
        call_args = mock_db_manager.fts_search.call_args
        sanitized_query = call_args.kwargs['query']
        
        # Verify plus signs were escaped
        assert "\\+" in sanitized_query
        
        # Verify results were returned
        assert len(results) == 1
    
    @pytest.mark.asyncio
    async def test_query_with_dot(self, search_service, mock_db_manager):
        """Test that queries with dots work correctly."""
        # Setup mock results
        mock_results = [
            {"id": "1", "content": "file.txt", "doc_id": "doc1"},
        ]
        mock_db_manager.fts_search.return_value = _make_search_results(mock_results, source="fts")
        
        # Execute search with dot
        query = "file.txt"
        results = await search_service.fts_search(
            query_fts=query,
            limit=10
        )
        
        # Verify search was called with sanitized query
        mock_db_manager.fts_search.assert_called_once()
        call_args = mock_db_manager.fts_search.call_args
        sanitized_query = call_args.kwargs['query']
        
        # Verify dots were escaped
        assert "\\." in sanitized_query
        
        # Verify results were returned
        assert len(results) == 1
    
    @pytest.mark.asyncio
    async def test_query_with_caret(self, search_service, mock_db_manager):
        """Test that queries with caret symbols work correctly."""
        # Setup mock results
        mock_results = [
            {"id": "1", "content": "XOR operation", "doc_id": "doc1"},
        ]
        mock_db_manager.fts_search.return_value = _make_search_results(mock_results, source="fts")
        
        # Execute search with caret
        query = "a ^ b"
        results = await search_service.fts_search(
            query_fts=query,
            limit=10
        )
        
        # Verify search was called with sanitized query
        mock_db_manager.fts_search.assert_called_once()
        call_args = mock_db_manager.fts_search.call_args
        sanitized_query = call_args.kwargs['query']
        
        # Verify caret was escaped
        assert "\\^" in sanitized_query
        
        # Verify results were returned
        assert len(results) == 1
    
    @pytest.mark.asyncio
    async def test_query_with_dollar_sign(self, search_service, mock_db_manager):
        """Test that queries with dollar signs work correctly."""
        # Setup mock results
        mock_results = [
            {"id": "1", "content": "price $100", "doc_id": "doc1"},
        ]
        mock_db_manager.fts_search.return_value = _make_search_results(mock_results, source="fts")
        
        # Execute search with dollar sign
        query = "$100"
        results = await search_service.fts_search(
            query_fts=query,
            limit=10
        )
        
        # Verify search was called with sanitized query
        mock_db_manager.fts_search.assert_called_once()
        call_args = mock_db_manager.fts_search.call_args
        sanitized_query = call_args.kwargs['query']
        
        # Verify dollar sign was escaped
        assert "\\$" in sanitized_query
        
        # Verify results were returned
        assert len(results) == 1
    
    @pytest.mark.asyncio
    async def test_query_with_pipe(self, search_service, mock_db_manager):
        """Test that queries with pipe symbols work correctly."""
        # Setup mock results
        mock_results = [
            {"id": "1", "content": "OR operation", "doc_id": "doc1"},
        ]
        mock_db_manager.fts_search.return_value = _make_search_results(mock_results, source="fts")
        
        # Execute search with pipe
        query = "a | b"
        results = await search_service.fts_search(
            query_fts=query,
            limit=10
        )
        
        # Verify search was called with sanitized query
        mock_db_manager.fts_search.assert_called_once()
        call_args = mock_db_manager.fts_search.call_args
        sanitized_query = call_args.kwargs['query']
        
        # Verify pipe was escaped
        assert "\\|" in sanitized_query
        
        # Verify results were returned
        assert len(results) == 1


class TestSanitizationLogging:
    """Test that sanitization is properly logged."""
    
    @pytest.mark.asyncio
    async def test_sanitization_is_logged(self, search_service, mock_db_manager, caplog):
        """Test that query sanitization is logged when query is changed."""
        import logging
        caplog.set_level(logging.INFO)
        
        # Setup mock results
        mock_results = [
            {"id": "1", "content": "result", "doc_id": "doc1"},
        ]
        mock_db_manager.fts_search.return_value = _make_search_results(mock_results, source="fts")
        
        # Execute search with special characters
        query = "How does this work?"
        await search_service.fts_search(
            query_fts=query,
            limit=10
        )
        
        # Verify sanitization was logged
        assert any("Query sanitized" in record.message for record in caplog.records)
        assert any("How does this work?" in record.message for record in caplog.records)
    
    @pytest.mark.asyncio
    async def test_no_log_when_query_unchanged(self, search_service, mock_db_manager, caplog):
        """Test that no log is generated when query doesn't need sanitization."""
        import logging
        caplog.set_level(logging.INFO)
        
        # Setup mock results
        mock_results = [
            {"id": "1", "content": "result", "doc_id": "doc1"},
        ]
        mock_db_manager.fts_search.return_value = _make_search_results(mock_results, source="fts")
        
        # Execute search without special characters
        query = "simple query"
        await search_service.fts_search(
            query_fts=query,
            limit=10
        )
        
        # Verify no sanitization log (query was unchanged)
        sanitization_logs = [r for r in caplog.records if "Query sanitized" in r.message]
        assert len(sanitization_logs) == 0
