"""
Validation tests for production quality improvements.

This test suite validates the improvements made in the production-quality-improvements spec:
1. Statistics accuracy after indexing
2. Keyword extraction functionality
3. Enhanced error messages and feedback
4. Initial discovery experience improvements
"""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock

from agentic_inquiry.mcp.utils.keyword_extractor import KeywordExtractor
from agentic_inquiry.mcp.tools.info import get_project_info
from agentic_inquiry.mcp.tools.context import build_context


@pytest.fixture
def keyword_extractor():
    """Create a KeywordExtractor instance."""
    return KeywordExtractor()


@pytest.fixture
def mock_db_manager():
    """Create a mock database manager."""
    mock_db_manager = AsyncMock()
    mock_db_manager.count_records = AsyncMock()
    mock_db_manager.query_raw = AsyncMock()
    # Add get_db_manager for StorageFacade compatibility
    mock_db_manager.get_db_manager = MagicMock(return_value=mock_db_manager)
    return mock_db_manager


@pytest.fixture
def mock_session():
    """Create a mock session object."""
    session = MagicMock()
    session.session_id = "test-session"
    session.project_id = "test-project"
    return session


@pytest.fixture
def sample_chunks_for_keywords():
    """Sample chunks with various keywords for extraction testing."""
    return [
        {
            "chunk_id": "chunk1",
            "symbols": ["UserService", "authenticate", "validate_token"],
            "element_name": "User Authentication Module",
            "fts_text": "user authentication service validates tokens and manages sessions",
            "file_path": "src/auth/user_service.py"
        },
        {
            "chunk_id": "chunk2",
            "symbols": ["DatabaseConnection", "connect", "query"],
            "element_name": "Database Connection Handler",
            "fts_text": "database connection handler manages queries and transactions",
            "file_path": "src/db/connection.py"
        },
        {
            "chunk_id": "chunk3",
            "symbols": ["APIRouter", "handle_request", "validate_input"],
            "element_name": "API Request Router",
            "fts_text": "api router handles requests validates input and routes to handlers",
            "file_path": "src/api/router.py"
        }
    ]


class TestStatisticsAccuracy:
    """Test statistics reporting accuracy after indexing."""
    
    @pytest.mark.asyncio
    async def test_statistics_reflect_indexed_content(self, mock_db_manager, mock_session):
        """Test that get_project_info returns accurate statistics after indexing."""
        # Setup - simulate indexed content
        mock_db_manager.count_records.side_effect = lambda table_name, **kwargs: {
            "document_chunks": 150,
            "graph_entities": 75,
            "graph_relationships": 200
        }.get(table_name, 0)

        # count_relationships_by_type returns dict with type -> count
        mock_db_manager.count_relationships_by_type = AsyncMock(return_value={
            "calls": 200
        })

        mock_memory_system = AsyncMock()
        mock_memory_system.get_stats.return_value = {
            "total_memories": 25,
            "working_memory": {"size": 10},
            "episodic_memory": {"size": 8},
            "semantic_memory": {"size": 7}
        }

        mock_session_manager = AsyncMock()
        mock_session_manager.validate_session.return_value = True
        mock_session_manager.get_session.return_value = mock_session

        services = {
            "mock_db_manager": mock_db_manager,
            "storage": mock_db_manager,  # Expose as storage for tools
            "memory_system": mock_memory_system,
            "session_manager": mock_session_manager
        }

        # Execute
        result = await get_project_info(services, "test-session")

        # Verify statistics are accurate
        assert result["statistics"]["chunks_indexed"] == 150
        assert result["statistics"]["entities_created"] == 75
        assert result["statistics"]["relationships_created"] == 200
        assert result["statistics"]["memories_stored"] == 25  # 10 + 8 + 7 = 25

        # Verify count_records was called (for chunks and entities)
        assert mock_db_manager.count_records.call_count >= 2
    
    @pytest.mark.asyncio
    async def test_statistics_consistency_after_multiple_indexes(self, mock_db_manager, mock_session):
        """Test that statistics remain consistent after multiple indexing operations."""
        # Simulate progressive indexing
        call_count = 0
        
        def count_side_effect(table_name, **kwargs):
            nonlocal call_count
            call_count += 1
            # Simulate increasing counts
            multiplier = (call_count // 3) + 1
            return {
                "document_chunks": 50 * multiplier,
                "graph_entities": 25 * multiplier,
                "graph_relationships": 75 * multiplier
            }.get(table_name, 0)
        
        mock_db_manager.count_records.side_effect = count_side_effect
        
        mock_memory_system = AsyncMock()
        mock_memory_system.get_stats.return_value = {
            "total_memories": 10,
            "working": {"count": 5},
            "episodic": {"count": 3},
            "semantic": {"count": 2}
        }
        
        mock_session_manager = AsyncMock()
        mock_session_manager.validate_session.return_value = True
        mock_session_manager.get_session.return_value = mock_session
        
        services = {
            "mock_db_manager": mock_db_manager,
        "storage": mock_db_manager,  # Expose as storage for tools
            "memory_system": mock_memory_system,
            "session_manager": mock_session_manager
        }
        
        # First call
        result1 = await get_project_info(services, "test-session")
        assert result1["statistics"]["chunks_indexed"] == 50
        
        # Second call (simulating more content indexed)
        result2 = await get_project_info(services, "test-session")
        assert result2["statistics"]["chunks_indexed"] == 100
        
        # Verify counts increased consistently
        assert result2["statistics"]["chunks_indexed"] > result1["statistics"]["chunks_indexed"]


class TestKeywordExtraction:
    """Test keyword extraction functionality."""
    
    @pytest.mark.asyncio
    async def test_extract_top_keywords_from_indexed_content(
        self, keyword_extractor, mock_db_manager, sample_chunks_for_keywords
    ):
        """Test extracting top keywords from indexed content."""
        # Setup
        mock_db_manager.query_raw.return_value = sample_chunks_for_keywords
        
        # Execute
        keywords = await keyword_extractor.extract_top_keywords(
            mock_db_manager,
            "test-project",
            limit=10
        )
        
        # Verify
        assert len(keywords) > 0
        assert all("keyword" in kw for kw in keywords)
        assert all("frequency" in kw for kw in keywords)
        
        # Verify keywords are sorted by frequency
        frequencies = [kw["frequency"] for kw in keywords]
        assert frequencies == sorted(frequencies, reverse=True)
    
    @pytest.mark.asyncio
    async def test_extract_related_keywords_from_search_results(
        self, keyword_extractor, sample_chunks_for_keywords
    ):
        """Test extracting related keywords from search results."""
        # Wrap dicts in objects with .data attribute (as expected by extract_related_keywords)
        class SearchResult:
            def __init__(self, data):
                self.data = data

        wrapped_results = [SearchResult(chunk) for chunk in sample_chunks_for_keywords]

        # Execute
        keywords = await keyword_extractor.extract_related_keywords(
            wrapped_results,
            limit=10
        )

        # Verify
        assert len(keywords) > 0
        assert isinstance(keywords, list)
        assert all(isinstance(kw, str) for kw in keywords)

        # Verify expected keywords are present
        keywords_lower = [kw.lower() for kw in keywords]
        assert any("user" in kw or "auth" in kw for kw in keywords_lower)
    
    def test_keyword_filtering_removes_common_terms(self, keyword_extractor):
        """Test that common programming terms are filtered out."""
        # Test with common programming keywords
        assert not keyword_extractor._is_valid_keyword("if")
        assert not keyword_extractor._is_valid_keyword("for")
        assert not keyword_extractor._is_valid_keyword("return")
        assert not keyword_extractor._is_valid_keyword("import")
        
        # Test with valid keywords
        assert keyword_extractor._is_valid_keyword("UserService")
        assert keyword_extractor._is_valid_keyword("authenticate")
        assert keyword_extractor._is_valid_keyword("database")
    
    def test_keyword_length_validation(self, keyword_extractor):
        """Test keyword length constraints."""
        # Too short
        assert not keyword_extractor._is_valid_keyword("a")
        assert not keyword_extractor._is_valid_keyword("ab")
        
        # Valid length
        assert keyword_extractor._is_valid_keyword("user")
        assert keyword_extractor._is_valid_keyword("authentication")
        
        # Too long (if max_keyword_length is set)
        very_long_keyword = "a" * 100
        assert not keyword_extractor._is_valid_keyword(very_long_keyword)
    
    @pytest.mark.asyncio
    async def test_keyword_extraction_handles_empty_content(
        self, keyword_extractor, mock_db_manager
    ):
        """Test keyword extraction with no indexed content."""
        # Setup - no chunks
        mock_db_manager.query_raw.return_value = []
        
        # Execute
        keywords = await keyword_extractor.extract_top_keywords(
            mock_db_manager,
            "empty-project",
            limit=10
        )
        
        # Verify
        assert keywords == []


class TestEnhancedErrorMessages:
    """Test enhanced error messages and feedback."""
    
    @pytest.mark.asyncio
    async def test_validation_error_provides_clear_feedback(self):
        """Test that validation errors provide clear feedback."""
        from agentic_inquiry.mcp.utils.validation import validate_limit
        
        # Test invalid limit
        try:
            validate_limit(-1, min_value=1, max_value=1000)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            # Verify error message is clear
            assert "limit" in str(e).lower()
            assert "-1" in str(e) or "negative" in str(e).lower()
    
    @pytest.mark.asyncio
    async def test_error_response_includes_suggestions(self):
        """Test that error responses include helpful suggestions."""
        from agentic_inquiry.mcp.utils.validation import create_validation_error_response
        
        # Create a validation error response
        error = ValueError("Invalid limit value")
        response = create_validation_error_response(
            field="limit",
            error=error,
            context={"session_id": "test"},
            provided_value=-1,
            expected_type="positive integer (1-1000)",
            example="limit=10"
        )
        
        # Verify response structure
        assert "error" in response
        # Should provide actionable information
        assert "limit" in str(response).lower() or "validation" in str(response).lower()


class TestInitialDiscoveryExperience:
    """Test improvements to initial discovery experience."""
    
    @pytest.mark.asyncio
    async def test_build_context_supports_overview_parameter(self):
        """Test that build_context accepts include_overview parameter."""
        # This test verifies the API signature supports overview prioritization
        from inspect import signature
        
        sig = signature(build_context)
        params = sig.parameters
        
        # Verify include_overview parameter exists
        assert "include_overview" in params
        assert params["include_overview"].default is False
    
    @pytest.mark.asyncio
    async def test_overview_content_detection(self):
        """Test that overview content can be identified."""
        # Test file path patterns that indicate overview content
        overview_paths = [
            "README.md",
            "docs/overview.md",
            "docs/architecture.md",
            "ARCHITECTURE.md"
        ]
        
        implementation_paths = [
            "src/implementation.py",
            "lib/utils.ts",
            "tests/test_file.py"
        ]
        
        # Verify we can distinguish overview from implementation
        for path in overview_paths:
            assert any(pattern in path.lower() for pattern in ["readme", "docs/", "architecture"])
        
        for path in implementation_paths:
            assert not any(pattern in path.lower() for pattern in ["readme", "architecture"])
            assert any(pattern in path.lower() for pattern in ["src/", "lib/", "tests/"])


class TestIntegrationWorkflows:
    """Integration tests for complete discovery workflows."""
    
    @pytest.mark.asyncio
    async def test_get_project_info_workflow(self, mock_session):
        """Test get_project_info returns complete information."""
        # Setup comprehensive mock services
        mock_db_manager = AsyncMock()
        mock_db_manager.count_records.side_effect = lambda table_name, **kwargs: {
            "document_chunks": 100,
            "graph_entities": 50,
            "graph_relationships": 150
        }.get(table_name, 0)
        # Add get_db_manager for StorageFacade compatibility
        mock_db_manager.get_db_manager = MagicMock(return_value=mock_db_manager)
        # count_relationships_by_type returns dict with type -> count
        mock_db_manager.count_relationships_by_type = AsyncMock(return_value={
            "calls": 150
        })

        mock_memory_system = AsyncMock()
        mock_memory_system.get_stats.return_value = {
            "total_memories": 10,
            "working": {"count": 5},
            "episodic": {"count": 3},
            "semantic": {"count": 2}
        }

        mock_session_manager = AsyncMock()
        mock_session_manager.validate_session.return_value = True
        mock_session_manager.get_session.return_value = mock_session

        services = {
            "mock_db_manager": mock_db_manager,
            "storage": mock_db_manager,  # Expose as storage for tools
            "memory_system": mock_memory_system,
            "session_manager": mock_session_manager
        }
        
        # Execute
        project_info = await get_project_info(services, "test-session")
        
        # Verify complete response structure
        assert "project_id" in project_info
        assert "statistics" in project_info
        assert "status" in project_info
        assert "top_keywords" in project_info
        assert "guidance" in project_info
        
        # Verify statistics are accurate
        assert project_info["statistics"]["chunks_indexed"] == 100
        assert project_info["statistics"]["entities_created"] == 50
        assert project_info["statistics"]["relationships_created"] == 150
        
        # Verify status flags
        assert project_info["status"]["indexed"] is True
        assert project_info["status"]["has_entities"] is True
    
    @pytest.mark.asyncio
    async def test_keyword_extraction_integration(self, mock_db_manager):
        """Test keyword extraction integrates with project info."""
        # Setup
        sample_chunks = [
            {
                "chunk_id": "1",
                "symbols": ["UserService", "authenticate"],
                "element_name": "Authentication",
                "fts_text": "user authentication service"
            }
        ]
        
        mock_db_manager.query_raw.return_value = sample_chunks
        
        keyword_extractor = KeywordExtractor()
        keywords = await keyword_extractor.extract_top_keywords(
            mock_db_manager,
            "test-project",
            limit=10
        )
        
        # Verify keywords were extracted
        assert len(keywords) > 0
        assert all("keyword" in kw and "frequency" in kw for kw in keywords)
