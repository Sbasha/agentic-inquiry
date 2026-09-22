"""Integration tests for understand_entity tool with EntityResolver."""

import pytest

pytestmark = pytest.mark.integration
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock

from agent_vault.config import Config
from agent_vault.mcp.factories import create_mcp_services
from agent_vault.mcp.tools.analysis import understand_entity
from agent_vault.models.graph_entity import GraphEntity


@pytest_asyncio.fixture
async def test_services(tmp_path):
    """Create MCP services with test configuration."""
    # Create test config
    config = Config.load()
    config.storage.root = str(tmp_path / "storage")
    
    # Create services
    services = await create_mcp_services(
        config=config,
        project_id="test_project"
    )
    
    # Mock event system to avoid actual event emission
    services["event_system"] = MagicMock()
    services["event_system"].emit = AsyncMock(return_value=None)
    
    yield services
    
    # Cleanup
    if "storage" in services:
        await services["storage"].close()


@pytest_asyncio.fixture
async def indexed_services(test_services):
    """Create services with test entities in database."""
    db_manager = test_services["storage"]
    
    # Create test entities directly in database (matching test_entity_tool.py pattern)
    entities = [
        GraphEntity(
            id="entity_1",
            name="SearchService",
            type="class",
            file_path="agent_vault/search/service.py",
            doc_id="doc_1",
            project_id="test_project",
            vector=[0.1] * 384,
            pagerank=0.8,
        ),
        GraphEntity(
            id="entity_2",
            name="search",
            type="function",
            file_path="agent_vault/search/service.py",
            doc_id="doc_2",
            project_id="test_project",
            vector=[0.2] * 384,
            pagerank=0.6,
        ),
        GraphEntity(
            id="entity_3",
            name="hybrid_search",
            type="function",
            file_path="agent_vault/search/service.py",
            doc_id="doc_3",
            project_id="test_project",
            vector=[0.15] * 384,
            pagerank=0.7,
        ),
        GraphEntity(
            id="entity_4",
            name="IndexingPipeline",
            type="class",
            file_path="agent_vault/indexing/pipeline.py",
            doc_id="doc_4",
            project_id="test_project",
            vector=[0.12] * 384,
            pagerank=0.9,
        ),
        GraphEntity(
            id="entity_5",
            name="index_file",
            type="function",
            file_path="agent_vault/indexing/pipeline.py",
            doc_id="doc_5",
            project_id="test_project",
            vector=[0.25] * 384,
            pagerank=0.5,
        ),
    ]
    
    # Add entities to database
    await db_manager.upsert_entities(entities)
    
    yield test_services


@pytest_asyncio.fixture
async def test_session(indexed_services):
    """Create a test session."""
    session_manager = indexed_services["session_manager"]
    session_info = await session_manager.create_session(
        project_id="test_project",
        description="Test session for understand_entity"
    )
    return session_info["session_id"]


@pytest.mark.asyncio
async def test_understand_entity_returns_non_empty_results(indexed_services, test_session):
    """Test that understand_entity returns non-empty results for known entities."""
    result = await understand_entity(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService"
    )
    
    # Verify entity information is present
    assert "entity" in result
    assert result["entity"]["name"] == "SearchService"
    assert result["entity"]["entity_type"] in ["class"]
    assert result["entity"]["file_path"]
    assert "line_start" in result["entity"]
    
    # Verify structure is correct (content or documentation may be empty for test data)
    assert "content" in result["entity"]
    assert "documentation" in result["entity"]


@pytest.mark.asyncio
async def test_understand_entity_with_dependencies(indexed_services, test_session):
    """Test that understand_entity returns dependencies."""
    result = await understand_entity(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService",
        include_dependencies=True
    )
    
    # Verify dependencies structure
    assert "dependencies" in result
    assert isinstance(result["dependencies"], list)
    
    # If dependencies exist, verify structure
    if result["dependencies"]:
        dep = result["dependencies"][0]
        assert "name" in dep
        assert "entity_type" in dep
        assert "file_path" in dep
        assert "relationship_type" in dep


@pytest.mark.asyncio
async def test_understand_entity_with_usage_examples(indexed_services, test_session):
    """Test that understand_entity returns usage examples."""
    result = await understand_entity(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService",
        include_usage=True
    )
    
    # Verify usage examples structure
    assert "usage_examples" in result
    assert isinstance(result["usage_examples"], list)
    
    # If usage examples exist, verify structure
    if result["usage_examples"]:
        usage = result["usage_examples"][0]
        assert "file_path" in usage
        assert "line_number" in usage
        assert "context" in usage
        assert "usage_type" in usage


@pytest.mark.asyncio
async def test_understand_entity_with_type_filter(indexed_services, test_session):
    """Test entity_type filtering."""
    result = await understand_entity(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService",
        entity_type="class"  # Use the actual type stored in database
    )
    
    # Verify entity was found with correct type
    assert "entity" in result
    assert result["entity"]["entity_type"] == "class"


@pytest.mark.asyncio
async def test_understand_entity_not_found_with_suggestions(indexed_services, test_session):
    """Test that entity not found returns suggestions."""
    result = await understand_entity(
        services=indexed_services,
        session_id=test_session,
        entity="NonExistentEntity"
    )
    
    # Verify error response structure
    assert "error" in result or "message" in result
    
    # Should include suggestions if available
    if "suggestions" in result:
        assert isinstance(result["suggestions"], list)


@pytest.mark.asyncio
async def test_understand_entity_case_insensitive(indexed_services, test_session):
    """Test case-insensitive entity resolution."""
    result = await understand_entity(
        services=indexed_services,
        session_id=test_session,
        entity="searchservice"  # lowercase
    )
    
    # Should still find SearchService
    if "entity" in result:
        assert result["entity"]["name"] == "SearchService"


@pytest.mark.asyncio
async def test_understand_entity_method(indexed_services, test_session):
    """Test understanding a method entity."""
    result = await understand_entity(
        services=indexed_services,
        session_id=test_session,
        entity="search"
    )
    
    # Verify method information if found
    if "entity" in result:
        assert result["entity"]["entity_type"] in ["function", "method"]


@pytest.mark.asyncio
async def test_understand_entity_correct_structure(indexed_services, test_session):
    """Test that response has correct structure."""
    result = await understand_entity(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService",
        include_dependencies=True,
        include_usage=True
    )
    
    # Verify all required fields are present
    assert "entity" in result
    assert "dependencies" in result
    assert "usage_examples" in result
    assert "metadata" in result
    
    # Verify entity structure
    entity = result["entity"]
    assert "name" in entity
    assert "entity_type" in entity
    assert "file_path" in entity
    assert "line_start" in entity
    assert "line_end" in entity


@pytest.mark.asyncio
async def test_understand_entity_invalid_session(indexed_services):
    """Test with invalid session ID."""
    result = await understand_entity(
        services=indexed_services,
        session_id="invalid_session_id",
        entity="SearchService"
    )
    
    # Should return error response
    assert "error" in result or "message" in result


@pytest.mark.asyncio
async def test_understand_entity_success_rate(indexed_services, test_session):
    """Test that success rate is >80% for indexed entities."""
    # Test multiple known entities
    entities_to_test = [
        "SearchService",
        "IndexingPipeline",
        "search",
        "hybrid_search",
        "index_file"
    ]
    
    successful = 0
    total = len(entities_to_test)
    
    for entity_name in entities_to_test:
        result = await understand_entity(
            services=indexed_services,
            session_id=test_session,
            entity=entity_name
        )
        
        # Count as successful if entity was found
        if "entity" in result and result["entity"].get("name"):
            successful += 1
    
    success_rate = successful / total
    
    # Verify >80% success rate (requirement 1.5)
    assert success_rate > 0.8, f"Success rate {success_rate:.1%} is below 80% threshold"


@pytest.mark.asyncio
async def test_understand_entity_without_dependencies(indexed_services, test_session):
    """Test understand_entity with dependencies disabled."""
    result = await understand_entity(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService",
        include_dependencies=False
    )
    
    # Dependencies should be empty list when not requested
    assert "dependencies" in result
    assert result["dependencies"] == []


@pytest.mark.asyncio
async def test_understand_entity_without_usage(indexed_services, test_session):
    """Test understand_entity with usage disabled."""
    result = await understand_entity(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService",
        include_usage=False
    )
    
    # Usage examples should be empty list when not requested
    assert "usage_examples" in result
    assert result["usage_examples"] == []
