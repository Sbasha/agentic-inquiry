"""Tests for entity resolver service."""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock

from agentic_inquiry.mcp.services.entity_resolver import (
    EntityResolver,
    EntityNotFoundError,
)


@pytest.fixture
def mock_db_manager():
    """Create mock database manager."""
    manager = AsyncMock()
    return manager


@pytest.fixture
def mock_storage_facade(mock_db_manager):
    """Create mock StorageFacade that wraps the mock_db_manager."""
    mock_storage = MagicMock()
    mock_storage.get_db_manager = MagicMock(return_value=mock_db_manager)
    # EntityResolver calls these methods directly on db_manager (StorageFacade)
    # Initialize with empty AsyncMock - tests will override with specific return values
    mock_storage.query_entities = AsyncMock(return_value=[])
    mock_storage.query_relationships = AsyncMock(return_value=[])
    return mock_storage


@pytest.fixture
def mock_config():
    """Create mock config with entity resolution settings."""
    config = MagicMock()

    # Entity resolution config
    config.entity_resolution.case_insensitive = True
    config.entity_resolution.cache_enabled = True
    config.entity_resolution.cache_ttl_seconds = 3600

    # Fuzzy matching config
    config.entity_resolution.fuzzy_matching.enabled = True
    config.entity_resolution.fuzzy_matching.threshold = 0.8

    # MCP query limits
    config.mcp.query.default_limit = 1000
    config.mcp.query.traversal_limit = 100

    return config


@pytest.fixture
def entity_resolver(mock_storage_facade, mock_config):
    """Create entity resolver instance."""
    return EntityResolver(db_manager=mock_storage_facade, config=mock_config)


@pytest.mark.asyncio
async def test_exact_match(entity_resolver, mock_storage_facade):
    """Test exact entity name match."""
    # Setup mock response
    mock_storage_facade.query_entities = AsyncMock(
        return_value=[
            {
                "id": "entity-1",
                "name": "SearchService",
                "type": "class",
                "file_path": "agentic_inquiry/search/service.py",
                "line_start": 10,
                "line_end": 100,
            }
        ]
    )

    # Resolve entity
    entity = await entity_resolver.resolve_entity(
        entity_name="SearchService", project_id="test-project"
    )

    # Verify result
    assert entity is not None
    assert entity.name == "SearchService"
    assert entity.entity_type == "class"
    assert entity.file_path == "agentic_inquiry/search/service.py"


@pytest.mark.asyncio
async def test_case_insensitive_match(entity_resolver, mock_storage_facade):
    """Test case-insensitive matching."""
    # Setup mock response - first call returns empty, second returns results
    mock_storage_facade.query_entities = AsyncMock(
        side_effect=[
            [],  # Exact match fails
            [
                {  # Case-insensitive match succeeds
                    "id": "entity-1",
                    "name": "SearchService",
                    "type": "class",
                    "file_path": "agentic_inquiry/search/service.py",
                    "line_start": 10,
                    "line_end": 100,
                }
            ],
        ]
    )

    # Resolve entity with different case
    entity = await entity_resolver.resolve_entity(
        entity_name="searchservice", project_id="test-project"
    )

    # Verify result
    assert entity is not None
    assert entity.name == "SearchService"
    assert entity.entity_type == "class"
    assert entity.file_path == "agentic_inquiry/search/service.py"


@pytest.mark.asyncio
async def test_fuzzy_match(entity_resolver, mock_storage_facade):
    """Test fuzzy matching with similarity threshold."""
    # Setup mock response - exact, camelcase, case-insensitive, module path fail;
    # fuzzy succeeds
    mock_storage_facade.query_entities = AsyncMock(
        side_effect=[
            [],  # Exact match fails
            [],  # CamelCase match fails (ILIKE pattern '%Search%Servic%')
            [],  # Case-insensitive match fails
            [],  # Module path match fails (ILIKE on qualified_name)
            [
                {  # Fuzzy match succeeds
                    "id": "entity-1",
                    "name": "SearchService",
                    "type": "class",
                    "file_path": "agentic_inquiry/search/service.py",
                    "line_start": 10,
                    "line_end": 100,
                }
            ],
        ]
    )

    # Resolve entity with typo
    entity = await entity_resolver.resolve_entity(
        entity_name="SearchServic",  # Missing 'e'
        project_id="test-project",
    )

    # Verify result
    assert entity is not None
    assert entity.name == "SearchService"
    assert entity.entity_type == "class"
    assert entity.file_path == "agentic_inquiry/search/service.py"


@pytest.mark.asyncio
async def test_entity_not_found(entity_resolver, mock_storage_facade):
    """Test entity not found with suggestions."""
    # Setup mock response - all strategies fail, then suggestions query
    mock_storage_facade.query_entities = AsyncMock(
        side_effect=[
            [],  # Exact match fails
            [],  # CamelCase match fails (ILIKE pattern '%Non%Existent%')
            [],  # Case-insensitive match fails
            [],  # Module path match fails (ILIKE on qualified_name)
            [],  # Fuzzy match fails
            [
                {  # Suggestions query
                    "id": "entity-1",
                    "name": "SearchService",
                    "type": "class",
                    "file_path": "agentic_inquiry/search/service.py",
                    "line_start": 10,
                    "line_end": 100,
                }
            ],
        ]
    )

    # Try to resolve non-existent entity
    with pytest.raises(EntityNotFoundError) as exc_info:
        await entity_resolver.resolve_entity(
            entity_name="NonExistent", project_id="test-project"
        )

    # Verify error has suggestions
    assert exc_info.value.entity_name == "NonExistent"
    assert len(exc_info.value.suggestions) > 0


@pytest.mark.asyncio
async def test_get_entity_dependencies(entity_resolver, mock_storage_facade):
    """Test getting entity dependencies."""
    # Setup mock responses
    mock_storage_facade.query_relationships = AsyncMock(
        return_value=[
            {"source_id": "entity-1", "target_id": "entity-2", "type": "imports"}
        ]
    )

    mock_storage_facade.query_entities = AsyncMock(
        return_value=[
            {
                "id": "entity-2",
                "name": "LanceDBManager",
                "type": "class",
                "file_path": "agentic_inquiry/database/lancedb_manager.py",
                "line_start": 20,
                "line_end": 200,
            }
        ]
    )

    # Get dependencies
    dependencies = await entity_resolver.get_entity_dependencies(
        entity_id="entity-1", project_id="test-project", depth=1
    )

    # Verify result
    assert len(dependencies) == 1
    assert dependencies[0].name == "LanceDBManager"
    assert dependencies[0].relationship_type == "imports"


@pytest.mark.asyncio
async def test_get_entity_usages(entity_resolver, mock_storage_facade):
    """Test getting entity usages."""
    # Setup mock responses
    mock_storage_facade.query_relationships = AsyncMock(
        return_value=[
            {"source_id": "entity-2", "target_id": "entity-1", "type": "calls"}
        ]
    )

    mock_storage_facade.query_entities = AsyncMock(
        return_value=[
            {
                "id": "entity-2",
                "name": "IndexingPipeline",
                "type": "class",
                "file_path": "agentic_inquiry/indexing/pipeline.py",
                "line_start": 30,
                "line_end": 300,
            }
        ]
    )

    # Get usages
    usages = await entity_resolver.get_entity_usages(
        entity_id="entity-1", project_id="test-project", limit=10
    )

    # Verify result
    assert len(usages) == 1
    assert usages[0].file_path == "agentic_inquiry/indexing/pipeline.py"
    assert usages[0].usage_type == "calls"


@pytest.mark.asyncio
async def test_cache_enabled(entity_resolver, mock_storage_facade):
    """Test that caching works when enabled."""
    # Setup mock response
    mock_storage_facade.query_entities = AsyncMock(
        return_value=[
            {
                "id": "entity-1",
                "name": "SearchService",
                "type": "class",
                "file_path": "agentic_inquiry/search/service.py",
                "line_start": 10,
                "line_end": 100,
            }
        ]
    )

    # First call - should query database
    entity1 = await entity_resolver.resolve_entity(
        entity_name="SearchService", project_id="test-project"
    )

    # Second call - should use cache
    entity2 = await entity_resolver.resolve_entity(
        entity_name="SearchService", project_id="test-project"
    )

    # Verify both calls returned same entity
    assert entity1.name == entity2.name

    # Verify database was only queried once
    assert mock_storage_facade.query_entities.call_count == 1


@pytest.mark.asyncio
async def test_entity_type_filter(entity_resolver, mock_storage_facade):
    """Test entity type filtering."""
    # Setup mock response
    mock_storage_facade.query_entities = AsyncMock(
        return_value=[
            {
                "id": "entity-1",
                "name": "SearchService",
                "type": "class",
                "file_path": "agentic_inquiry/search/service.py",
                "line_start": 10,
                "line_end": 100,
            }
        ]
    )

    # Resolve entity with type filter
    entity = await entity_resolver.resolve_entity(
        entity_name="SearchService", project_id="test-project", entity_type="class"
    )

    # Verify result
    assert entity is not None
    assert entity.name == "SearchService"
    assert entity.entity_type == "class"
    assert entity.file_path == "agentic_inquiry/search/service.py"

    # Verify filter was passed to query
    call_args = mock_storage_facade.query_entities.call_args
    assert call_args[1]["filters"]["type"] == "class"
