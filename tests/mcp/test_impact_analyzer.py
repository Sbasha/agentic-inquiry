"""Tests for impact analyzer service."""

import pytest

pytestmark = pytest.mark.unit

from unittest.mock import AsyncMock, MagicMock

from agentic_inquiry.mcp.services.impact_analyzer import ImpactAnalyzer
from agentic_inquiry.mcp.services.entity_resolver import (
    EntityDefinition,
    EntityNotFoundError,
)


@pytest.fixture
def mock_db_manager():
    """Create mock database manager."""
    manager = AsyncMock()
    return manager


@pytest.fixture
def mock_storage_facade(mock_db_manager):
    """Create mock StorageFacade wrapping the mock_db_manager.

    ImpactAnalyzer expects StorageFacade and extracts the LanceDBManager via
    the get_db_manager() method.
    """
    mock_storage = MagicMock()
    mock_storage.get_db_manager = MagicMock(return_value=mock_db_manager)
    # ImpactAnalyzer calls these methods directly on db_manager (StorageFacade)
    mock_storage.query_relationships = AsyncMock(return_value=[])
    mock_storage.query_entities = AsyncMock(return_value=[])
    mock_storage.advanced_filter = AsyncMock(return_value=[])
    return mock_storage


@pytest.fixture
def mock_entity_resolver():
    """Create mock entity resolver."""
    resolver = AsyncMock()
    return resolver


@pytest.fixture
def mock_config():
    """Create mock config with impact analysis settings."""
    config = MagicMock()

    # Impact analysis config (Phase 2: flattened into indexing config)
    config.indexing.impact_default_depth = 2
    config.indexing.impact_max_depth = 5
    config.indexing.impact_include_indirect = True

    # MCP query limits
    config.mcp.query.traversal_limit = 100
    config.mcp.query.tree_limit = 50
    config.mcp.query.batch_size = 100  # Batch size for entity lookups

    return config


@pytest.fixture
def impact_analyzer(mock_storage_facade, mock_entity_resolver, mock_config):
    """Create impact analyzer instance."""
    return ImpactAnalyzer(
        db_manager=mock_storage_facade,
        entity_resolver=mock_entity_resolver,
        config=mock_config,
    )


@pytest.mark.asyncio
async def test_direct_dependencies_depth_1(
    impact_analyzer, mock_entity_resolver, mock_storage_facade
):
    """Test impact analysis with depth=1 (direct dependencies only)."""
    # Setup mock entity resolution
    mock_entity_resolver.resolve_entity = AsyncMock(
        return_value=EntityDefinition(
            entity_id="entity-1",
            name="SearchService",
            entity_type="class",
            file_path="agentic_inquiry/search/service.py",
            line_start=10,
            line_end=100,
            content="class SearchService: ...",
            docstring="Search service class",
            metadata={},
        )
    )

    # Setup mock relationships - direct dependencies only
    mock_storage_facade.query_relationships = AsyncMock(
        return_value=[
            {"source_id": "entity-2", "target_id": "entity-1", "type": "imports"},
            {"source_id": "entity-3", "target_id": "entity-1", "type": "calls"},
        ]
    )

    # Setup mock entity queries - use a function to handle multiple calls
    entity_map = {
        "entity-1": [
            {
                "id": "entity-1",
                "name": "SearchService",
                "type": "class",
                "file_path": "agentic_inquiry/search/service.py",
            }
        ],
        "entity-2": [
            {
                "id": "entity-2",
                "name": "IndexingPipeline",
                "type": "class",
                "file_path": "agentic_inquiry/indexing/pipeline.py",
            }
        ],
        "entity-3": [
            {
                "id": "entity-3",
                "name": "ContextBuilder",
                "type": "class",
                "file_path": "agentic_inquiry/mcp/services/context_builder.py",
            }
        ],
    }

    async def mock_query_entities(project_id, filters=None, limit=None):
        if filters and "id" in filters:
            filter_value = filters["id"]
            # Handle both single ID and IN clause formats
            if isinstance(filter_value, tuple) and filter_value[0] == "IN":
                # IN clause: return entities for all IDs in the list
                entity_ids = filter_value[1]
                results = []
                for entity_id in entity_ids:
                    if entity_id in entity_map:
                        results.extend(entity_map[entity_id])
                return results
            else:
                # Single ID: backward compatibility
                return entity_map.get(filter_value, [])
        return []

    mock_storage_facade.query_entities = mock_query_entities

    # Analyze impact with depth=1
    impact = await impact_analyzer.analyze_impact(
        entity_name="SearchService",
        project_id="test-project",
        depth=1,
        include_indirect=True,
    )

    # Verify results
    assert impact.entity_name == "SearchService"
    assert impact.impact_radius > 0
    assert len(impact.affected_entities) > 0
    assert len(impact.affected_files) > 0
    assert impact.traversal_depth == 1


@pytest.mark.asyncio
async def test_transitive_dependencies_depth_3(
    impact_analyzer, mock_entity_resolver, mock_storage_facade
):
    """Test impact analysis with depth=3 (transitive dependencies)."""
    # Setup mock entity resolution
    mock_entity_resolver.resolve_entity = AsyncMock(
        return_value=EntityDefinition(
            entity_id="entity-1",
            name="SearchService",
            entity_type="class",
            file_path="agentic_inquiry/search/service.py",
            line_start=10,
            line_end=100,
            content="class SearchService: ...",
            docstring="Search service class",
            metadata={},
        )
    )

    # Setup mock relationships - return empty for all queries to simplify
    # We just need to verify depth is respected
    mock_storage_facade.query_relationships = AsyncMock(return_value=[])
    mock_storage_facade.query_entities = AsyncMock(return_value=[])

    # Analyze impact with depth=3
    impact = await impact_analyzer.analyze_impact(
        entity_name="SearchService",
        project_id="test-project",
        depth=3,
        include_indirect=True,
    )

    # Verify results - depth should be 3 even with no relationships
    assert impact.entity_name == "SearchService"
    assert impact.traversal_depth == 3


@pytest.mark.asyncio
async def test_circular_dependency_handling(
    impact_analyzer, mock_entity_resolver, mock_storage_facade
):
    """Test that circular dependencies don't cause infinite loops."""
    # Setup mock entity resolution
    mock_entity_resolver.resolve_entity = AsyncMock(
        return_value=EntityDefinition(
            entity_id="entity-1",
            name="ServiceA",
            entity_type="class",
            file_path="agentic_inquiry/services/a.py",
            line_start=10,
            line_end=100,
            content="class ServiceA: ...",
            docstring="Service A",
            metadata={},
        )
    )

    # Setup circular relationships: A -> B -> A (simple cycle)
    # The visited set should prevent infinite loops
    def relationship_side_effect(*args, **kwargs):
        filters = kwargs.get("filters", {})
        if "target_id" in filters:
            target = filters["target_id"]
            if target == "entity-1":
                return [
                    {
                        "source_id": "entity-2",
                        "target_id": "entity-1",
                        "type": "imports",
                    }
                ]
            elif target == "entity-2":
                return [
                    {
                        "source_id": "entity-1",
                        "target_id": "entity-2",
                        "type": "imports",
                    }
                ]  # Circular!
        elif "source_id" in filters:
            source = filters["source_id"]
            if source == "entity-1":
                return [
                    {
                        "source_id": "entity-1",
                        "target_id": "entity-2",
                        "type": "imports",
                    }
                ]
            elif source == "entity-2":
                return [
                    {
                        "source_id": "entity-2",
                        "target_id": "entity-1",
                        "type": "imports",
                    }
                ]  # Circular!
        return []

    mock_storage_facade.query_relationships = AsyncMock(
        side_effect=relationship_side_effect
    )

    # Setup mock entity queries - use a function to handle multiple calls
    entity_map = {
        "entity-1": [
            {
                "id": "entity-1",
                "name": "ServiceA",
                "type": "class",
                "file_path": "agentic_inquiry/services/a.py",
            }
        ],
        "entity-2": [
            {
                "id": "entity-2",
                "name": "ServiceB",
                "type": "class",
                "file_path": "agentic_inquiry/services/b.py",
            }
        ],
    }

    async def mock_query_entities(project_id, filters=None, limit=None):
        if filters and "id" in filters:
            filter_value = filters["id"]
            # Handle both single ID and IN clause formats
            if isinstance(filter_value, tuple) and filter_value[0] == "IN":
                # IN clause: return entities for all IDs in the list
                entity_ids = filter_value[1]
                results = []
                for entity_id in entity_ids:
                    if entity_id in entity_map:
                        results.extend(entity_map[entity_id])
                return results
            else:
                # Single ID: backward compatibility
                return entity_map.get(filter_value, [])
        return []

    mock_storage_facade.query_entities = mock_query_entities

    # Analyze impact - should terminate without infinite loop
    impact = await impact_analyzer.analyze_impact(
        entity_name="ServiceA",
        project_id="test-project",
        depth=5,
        include_indirect=True,
    )

    # Verify results - should have found entities but not infinite
    assert impact.entity_name == "ServiceA"
    assert impact.impact_radius < 100  # Should be small, not infinite


@pytest.mark.asyncio
async def test_incoming_relationships_only(
    impact_analyzer, mock_entity_resolver, mock_storage_facade
):
    """Test traversing incoming relationships (who depends on this)."""
    # Setup mock entity resolution
    mock_entity_resolver.resolve_entity = AsyncMock(
        return_value=EntityDefinition(
            entity_id="entity-1",
            name="SearchService",
            entity_type="class",
            file_path="agentic_inquiry/search/service.py",
            line_start=10,
            line_end=100,
            content="class SearchService: ...",
            docstring="Search service class",
            metadata={},
        )
    )

    # Setup mock relationships - only incoming
    async def relationship_side_effect(*args, **kwargs):
        filters = kwargs.get("filters", {})
        if "target_id" in filters and filters["target_id"] == "entity-1":
            return [
                {"source_id": "entity-2", "target_id": "entity-1", "type": "imports"},
                {"source_id": "entity-3", "target_id": "entity-1", "type": "calls"},
            ]
        return []

    mock_storage_facade.query_relationships = AsyncMock(
        side_effect=relationship_side_effect
    )

    # Setup mock entity queries - use a function to handle multiple calls
    entity_map = {
        "entity-1": [
            {
                "id": "entity-1",
                "name": "SearchService",
                "type": "class",
                "file_path": "agentic_inquiry/search/service.py",
            }
        ],
        "entity-2": [
            {
                "id": "entity-2",
                "name": "IndexingPipeline",
                "type": "class",
                "file_path": "agentic_inquiry/indexing/pipeline.py",
            }
        ],
        "entity-3": [
            {
                "id": "entity-3",
                "name": "ContextBuilder",
                "type": "class",
                "file_path": "agentic_inquiry/mcp/services/context_builder.py",
            }
        ],
    }

    async def mock_query_entities(project_id, filters=None, limit=None):
        if filters and "id" in filters:
            filter_value = filters["id"]
            # Handle both single ID and IN clause formats
            if isinstance(filter_value, tuple) and filter_value[0] == "IN":
                # IN clause: return entities for all IDs in the list
                entity_ids = filter_value[1]
                results = []
                for entity_id in entity_ids:
                    if entity_id in entity_map:
                        results.extend(entity_map[entity_id])
                return results
            else:
                # Single ID: backward compatibility
                return entity_map.get(filter_value, [])
        return []

    mock_storage_facade.query_entities = mock_query_entities

    # Analyze impact
    impact = await impact_analyzer.analyze_impact(
        entity_name="SearchService",
        project_id="test-project",
        depth=1,
        include_indirect=True,
    )

    # Verify results
    assert impact.impact_radius > 0
    assert "depends_on" in impact.relationship_types


@pytest.mark.asyncio
async def test_outgoing_relationships_only(
    impact_analyzer, mock_entity_resolver, mock_storage_facade
):
    """Test traversing outgoing relationships (what this depends on)."""
    # Setup mock entity resolution
    mock_entity_resolver.resolve_entity = AsyncMock(
        return_value=EntityDefinition(
            entity_id="entity-1",
            name="SearchService",
            entity_type="class",
            file_path="agentic_inquiry/search/service.py",
            line_start=10,
            line_end=100,
            content="class SearchService: ...",
            docstring="Search service class",
            metadata={},
        )
    )

    # Setup mock relationships - only outgoing
    async def relationship_side_effect(*args, **kwargs):
        filters = kwargs.get("filters", {})
        if "source_id" in filters and filters["source_id"] == "entity-1":
            return [
                {"source_id": "entity-1", "target_id": "entity-2", "type": "imports"},
                {"source_id": "entity-1", "target_id": "entity-3", "type": "calls"},
            ]
        return []

    mock_storage_facade.query_relationships = AsyncMock(
        side_effect=relationship_side_effect
    )

    # Setup mock entity queries - use a function to handle multiple calls
    entity_map = {
        "entity-1": [
            {
                "id": "entity-1",
                "name": "SearchService",
                "type": "class",
                "file_path": "agentic_inquiry/search/service.py",
            }
        ],
        "entity-2": [
            {
                "id": "entity-2",
                "name": "LanceDBManager",
                "type": "class",
                "file_path": "agentic_inquiry/database/lancedb_manager.py",
            }
        ],
        "entity-3": [
            {
                "id": "entity-3",
                "name": "EmbeddingService",
                "type": "class",
                "file_path": "agentic_inquiry/embeddings/service.py",
            }
        ],
    }

    async def mock_query_entities(project_id, filters=None, limit=None):
        if filters and "id" in filters:
            filter_value = filters["id"]
            # Handle both single ID and IN clause formats
            if isinstance(filter_value, tuple) and filter_value[0] == "IN":
                # IN clause: return entities for all IDs in the list
                entity_ids = filter_value[1]
                results = []
                for entity_id in entity_ids:
                    if entity_id in entity_map:
                        results.extend(entity_map[entity_id])
                return results
            else:
                # Single ID: backward compatibility
                return entity_map.get(filter_value, [])
        return []

    mock_storage_facade.query_entities = mock_query_entities

    # Analyze impact with include_indirect=False (only outgoing)
    impact = await impact_analyzer.analyze_impact(
        entity_name="SearchService",
        project_id="test-project",
        depth=1,
        include_indirect=False,
    )

    # Verify results - should have outgoing dependencies
    assert impact.impact_radius > 0
    assert "dependency" in impact.relationship_types


@pytest.mark.asyncio
async def test_max_depth_enforcement(
    impact_analyzer, mock_entity_resolver, mock_storage_facade
):
    """Test that max depth is enforced from configuration."""
    # Setup mock entity resolution
    mock_entity_resolver.resolve_entity = AsyncMock(
        return_value=EntityDefinition(
            entity_id="entity-1",
            name="SearchService",
            entity_type="class",
            file_path="agentic_inquiry/search/service.py",
            line_start=10,
            line_end=100,
            content="class SearchService: ...",
            docstring="Search service class",
            metadata={},
        )
    )

    # Setup mock relationships
    mock_storage_facade.query_relationships = AsyncMock(return_value=[])
    mock_storage_facade.query_entities = AsyncMock(return_value=[])

    # Try to analyze with depth > max_depth (5)
    impact = await impact_analyzer.analyze_impact(
        entity_name="SearchService",
        project_id="test-project",
        depth=10,  # Exceeds max_depth of 5
        include_indirect=True,
    )

    # Verify depth was capped at max_depth
    assert impact.traversal_depth == 5  # Should be capped at max_depth


@pytest.mark.asyncio
async def test_entity_not_found_raises_error(impact_analyzer, mock_entity_resolver):
    """Test that EntityNotFoundError is raised when entity doesn't exist."""
    # Setup mock entity resolution to return None
    mock_entity_resolver.resolve_entity = AsyncMock(return_value=None)

    # Try to analyze non-existent entity
    with pytest.raises(EntityNotFoundError):
        await impact_analyzer.analyze_impact(
            entity_name="NonExistent", project_id="test-project", depth=2
        )


@pytest.mark.asyncio
async def test_affected_files_grouping(
    impact_analyzer, mock_entity_resolver, mock_storage_facade
):
    """Test that affected entities are grouped by file."""
    # Setup mock entity resolution
    mock_entity_resolver.resolve_entity = AsyncMock(
        return_value=EntityDefinition(
            entity_id="entity-1",
            name="SearchService",
            entity_type="class",
            file_path="agentic_inquiry/search/service.py",
            line_start=10,
            line_end=100,
            content="class SearchService: ...",
            docstring="Search service class",
            metadata={},
        )
    )

    # Setup mock relationships - multiple entities in same file
    async def relationship_side_effect(*args, **kwargs):
        filters = kwargs.get("filters", {})
        if "target_id" in filters and filters["target_id"] == "entity-1":
            return [
                {"source_id": "entity-2", "target_id": "entity-1", "type": "imports"},
                {"source_id": "entity-3", "target_id": "entity-1", "type": "calls"},
            ]
        return []

    mock_storage_facade.query_relationships = AsyncMock(
        side_effect=relationship_side_effect
    )

    # Setup mock entity queries - both in same file - use function to handle multiple calls
    entity_map = {
        "entity-1": [
            {
                "id": "entity-1",
                "name": "SearchService",
                "type": "class",
                "file_path": "agentic_inquiry/search/service.py",
            }
        ],
        "entity-2": [
            {
                "id": "entity-2",
                "name": "IndexingPipeline",
                "type": "class",
                "file_path": "agentic_inquiry/indexing/pipeline.py",
            }
        ],
        "entity-3": [
            {
                "id": "entity-3",
                "name": "index_directory",
                "type": "function",
                "file_path": "agentic_inquiry/indexing/pipeline.py",
            }
        ],
    }

    async def mock_query_entities(project_id, filters=None, limit=None):
        if filters and "id" in filters:
            filter_value = filters["id"]
            # Handle both single ID and IN clause formats
            if isinstance(filter_value, tuple) and filter_value[0] == "IN":
                # IN clause: return entities for all IDs in the list
                entity_ids = filter_value[1]
                results = []
                for entity_id in entity_ids:
                    if entity_id in entity_map:
                        results.extend(entity_map[entity_id])
                return results
            else:
                # Single ID: backward compatibility
                return entity_map.get(filter_value, [])
        return []

    mock_storage_facade.query_entities = mock_query_entities

    # Analyze impact
    impact = await impact_analyzer.analyze_impact(
        entity_name="SearchService",
        project_id="test-project",
        depth=1,
        include_indirect=True,
    )

    # Verify files are grouped correctly
    assert "agentic_inquiry/indexing/pipeline.py" in impact.affected_files
    assert (
        impact.affected_files["agentic_inquiry/indexing/pipeline.py"] == 2
    )  # Two entities in same file


@pytest.mark.asyncio
async def test_relationship_types_counting(
    impact_analyzer, mock_entity_resolver, mock_storage_facade
):
    """Test that relationship types are counted correctly."""
    # Setup mock entity resolution
    mock_entity_resolver.resolve_entity = AsyncMock(
        return_value=EntityDefinition(
            entity_id="entity-1",
            name="SearchService",
            entity_type="class",
            file_path="agentic_inquiry/search/service.py",
            line_start=10,
            line_end=100,
            content="class SearchService: ...",
            docstring="Search service class",
            metadata={},
        )
    )

    # Setup mock relationships
    async def relationship_side_effect(*args, **kwargs):
        filters = kwargs.get("filters", {})
        if "target_id" in filters and filters["target_id"] == "entity-1":
            return [
                {"source_id": "entity-2", "target_id": "entity-1", "type": "imports"},
                {"source_id": "entity-3", "target_id": "entity-1", "type": "calls"},
            ]
        elif "source_id" in filters and filters["source_id"] == "entity-1":
            return [
                {"source_id": "entity-1", "target_id": "entity-4", "type": "imports"}
            ]
        return []

    mock_storage_facade.query_relationships = AsyncMock(
        side_effect=relationship_side_effect
    )

    # Setup mock entity queries - use function to handle multiple calls
    entity_map = {
        "entity-1": [
            {
                "id": "entity-1",
                "name": "SearchService",
                "type": "class",
                "file_path": "agentic_inquiry/search/service.py",
            }
        ],
        "entity-2": [
            {
                "id": "entity-2",
                "name": "IndexingPipeline",
                "type": "class",
                "file_path": "agentic_inquiry/indexing/pipeline.py",
            }
        ],
        "entity-3": [
            {
                "id": "entity-3",
                "name": "ContextBuilder",
                "type": "class",
                "file_path": "agentic_inquiry/mcp/services/context_builder.py",
            }
        ],
        "entity-4": [
            {
                "id": "entity-4",
                "name": "LanceDBManager",
                "type": "class",
                "file_path": "agentic_inquiry/database/lancedb_manager.py",
            }
        ],
    }

    async def mock_query_entities(project_id, filters=None, limit=None):
        if filters and "id" in filters:
            filter_value = filters["id"]
            # Handle both single ID and IN clause formats
            if isinstance(filter_value, tuple) and filter_value[0] == "IN":
                # IN clause: return entities for all IDs in the list
                entity_ids = filter_value[1]
                results = []
                for entity_id in entity_ids:
                    if entity_id in entity_map:
                        results.extend(entity_map[entity_id])
                return results
            else:
                # Single ID: backward compatibility
                return entity_map.get(filter_value, [])
        return []

    mock_storage_facade.query_entities = mock_query_entities

    # Analyze impact
    impact = await impact_analyzer.analyze_impact(
        entity_name="SearchService",
        project_id="test-project",
        depth=1,
        include_indirect=True,
    )

    # Verify relationship types are counted
    assert "depends_on" in impact.relationship_types
    assert "dependency" in impact.relationship_types
    assert impact.relationship_types["depends_on"] == 2  # Two incoming
    assert impact.relationship_types["dependency"] == 1  # One outgoing


@pytest.mark.asyncio
async def test_exact_depth_traversal_chain(
    impact_analyzer, mock_entity_resolver, mock_storage_facade
):
    """Test exact depth traversal with known 3-level chain: A→B→C→D.

    P0-2 verification test: Ensures depth=N returns exactly N levels.
    - depth=1: should find only B (direct dependency)
    - depth=2: should find B and C (2 levels)
    - depth=3: should find B, C, and D (3 levels)
    """
    # Setup mock entity resolution for A (root entity)
    mock_entity_resolver.resolve_entity = AsyncMock(
        return_value=EntityDefinition(
            entity_id="entity-A",
            name="RootClass",
            entity_type="class",
            file_path="agentic_inquiry/root.py",
            line_start=10,
            line_end=100,
            content="class RootClass: ...",
            docstring="Root class in chain",
            metadata={},
        )
    )

    # Setup mock relationships for linear chain: A→B→C→D
    # Each entity only has one dependency to create clean chain
    async def relationship_side_effect(*args, **kwargs):
        filters = kwargs.get("filters", {})
        # Incoming relationships (who depends on this entity)
        if "target_id" in filters:
            target = filters["target_id"]
            if target == "entity-A":
                return [
                    {
                        "source_id": "entity-B",
                        "target_id": "entity-A",
                        "type": "imports",
                    }
                ]
            elif target == "entity-B":
                return [
                    {
                        "source_id": "entity-C",
                        "target_id": "entity-B",
                        "type": "imports",
                    }
                ]
            elif target == "entity-C":
                return [
                    {
                        "source_id": "entity-D",
                        "target_id": "entity-C",
                        "type": "imports",
                    }
                ]
            elif target == "entity-D":
                return []  # D has no dependents (end of chain)
        return []

    mock_storage_facade.query_relationships = AsyncMock(
        side_effect=relationship_side_effect
    )

    # Setup mock entity queries for chain A→B→C→D
    entity_map = {
        "entity-A": [
            {
                "id": "entity-A",
                "name": "RootClass",
                "type": "class",
                "file_path": "agentic_inquiry/root.py",
            }
        ],
        "entity-B": [
            {
                "id": "entity-B",
                "name": "LevelOneClass",
                "type": "class",
                "file_path": "agentic_inquiry/level1.py",
            }
        ],
        "entity-C": [
            {
                "id": "entity-C",
                "name": "LevelTwoClass",
                "type": "class",
                "file_path": "agentic_inquiry/level2.py",
            }
        ],
        "entity-D": [
            {
                "id": "entity-D",
                "name": "LevelThreeClass",
                "type": "class",
                "file_path": "agentic_inquiry/level3.py",
            }
        ],
    }

    async def mock_query_entities(project_id, filters=None, limit=None):
        if filters and "id" in filters:
            filter_value = filters["id"]
            # Handle both single ID and IN clause formats
            if isinstance(filter_value, tuple) and filter_value[0] == "IN":
                # IN clause: return entities for all IDs in the list
                entity_ids = filter_value[1]
                results = []
                for entity_id in entity_ids:
                    if entity_id in entity_map:
                        results.extend(entity_map[entity_id])
                return results
            else:
                # Single ID: backward compatibility
                return entity_map.get(filter_value, [])
        return []

    mock_storage_facade.query_entities = mock_query_entities

    # Test depth=1: should find only B
    impact_depth1 = await impact_analyzer.analyze_impact(
        entity_name="RootClass",
        project_id="test-project",
        depth=1,
        include_indirect=True,
    )

    # Collect affected entity names (excluding root)
    # EntityReference is a dataclass with .name attribute
    affected_names_depth1 = {e.name for e in impact_depth1.affected_entities}

    # With depth=1, should only find direct dependency B
    assert "LevelOneClass" in affected_names_depth1, (
        f"depth=1 should find LevelOneClass, found: {affected_names_depth1}"
    )
    # Should NOT find deeper levels at depth=1
    assert "LevelTwoClass" not in affected_names_depth1, (
        f"depth=1 should NOT find LevelTwoClass (level 2), found: {affected_names_depth1}"
    )
    assert "LevelThreeClass" not in affected_names_depth1, (
        f"depth=1 should NOT find LevelThreeClass (level 3), found: {affected_names_depth1}"
    )

    # Test depth=2: should find B and C
    impact_depth2 = await impact_analyzer.analyze_impact(
        entity_name="RootClass",
        project_id="test-project",
        depth=2,
        include_indirect=True,
    )

    affected_names_depth2 = {e.name for e in impact_depth2.affected_entities}

    assert "LevelOneClass" in affected_names_depth2, (
        f"depth=2 should find LevelOneClass, found: {affected_names_depth2}"
    )
    assert "LevelTwoClass" in affected_names_depth2, (
        f"depth=2 should find LevelTwoClass, found: {affected_names_depth2}"
    )
    # Should NOT find level 3 at depth=2
    assert "LevelThreeClass" not in affected_names_depth2, (
        f"depth=2 should NOT find LevelThreeClass (level 3), found: {affected_names_depth2}"
    )

    # Test depth=3: should find B, C, and D
    impact_depth3 = await impact_analyzer.analyze_impact(
        entity_name="RootClass",
        project_id="test-project",
        depth=3,
        include_indirect=True,
    )

    affected_names_depth3 = {e.name for e in impact_depth3.affected_entities}

    assert "LevelOneClass" in affected_names_depth3, (
        f"depth=3 should find LevelOneClass, found: {affected_names_depth3}"
    )
    assert "LevelTwoClass" in affected_names_depth3, (
        f"depth=3 should find LevelTwoClass, found: {affected_names_depth3}"
    )
    assert "LevelThreeClass" in affected_names_depth3, (
        f"depth=3 should find LevelThreeClass, found: {affected_names_depth3}"
    )


# ===========================================================================
# T5.2: Performance Improvement Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_analyze_impact_batch_lookup(
    impact_analyzer, mock_entity_resolver, mock_storage_facade
):
    """Test that analyze_impact uses batched IN clause lookups for entity references.

    Verifies FR-1.6, FR-1.7: Batch lookup optimization
    """
    # Setup mock entity resolution
    mock_entity_resolver.resolve_entity = AsyncMock(
        return_value=EntityDefinition(
            entity_id="entity-1",
            name="ServiceA",
            entity_type="class",
            file_path="agentic_inquiry/services/a.py",
            line_start=10,
            line_end=100,
            content="class ServiceA: ...",
            docstring="Service A",
            metadata={},
        )
    )

    # Setup mock relationships - return 5 related entities
    mock_storage_facade.query_relationships = AsyncMock(
        return_value=[
            {"source_id": f"entity-{i}", "target_id": "entity-1", "type": "imports"}
            for i in range(2, 7)  # entity-2 through entity-6
        ]
    )

    # Track calls to query_entities to verify batching
    query_entities_calls = []

    async def mock_query_entities(project_id, filters=None, limit=None):
        query_entities_calls.append({"filters": filters, "limit": limit})

        # Return mock entities based on filter
        if filters and "id" in filters:
            filter_value = filters["id"]
            if isinstance(filter_value, tuple) and filter_value[0] == "IN":
                # Batch lookup with IN clause
                entity_ids = filter_value[1]
                return [
                    {
                        "id": eid,
                        "name": f"Entity{eid[-1]}",
                        "type": "class",
                        "file_path": f"agentic_inquiry/entity{eid[-1]}.py",
                    }
                    for eid in entity_ids
                ]
        return []

    mock_storage_facade.query_entities = mock_query_entities

    # Run impact analysis
    await impact_analyzer.analyze_impact(
        entity_name="ServiceA",
        project_id="test-project",
        depth=1,
        include_indirect=True,
    )

    # Verify that query_entities was called with IN clause (batched lookup)
    assert len(query_entities_calls) > 0, "query_entities should have been called"

    # Check that at least one call used IN clause for batching
    has_in_clause = any(
        call["filters"]
        and "id" in call["filters"]
        and isinstance(call["filters"]["id"], tuple)
        and call["filters"]["id"][0] == "IN"
        for call in query_entities_calls
    )
    assert has_in_clause, "Should use IN clause for batch entity lookup"


@pytest.mark.asyncio
async def test_analyze_impact_partial_results(
    impact_analyzer, mock_entity_resolver, mock_storage_facade
):
    """Test that analyze_impact returns partial results on timeout.

    Verifies AC-2.3: Partial results on timeout
    """
    import time
    from agentic_inquiry.mcp.services.impact_analyzer import PartialResultsException

    # Setup mock entity resolution
    mock_entity_resolver.resolve_entity = AsyncMock(
        return_value=EntityDefinition(
            entity_id="entity-1",
            name="ServiceA",
            entity_type="class",
            file_path="agentic_inquiry/services/a.py",
            line_start=10,
            line_end=100,
            content="class ServiceA: ...",
            docstring="Service A",
            metadata={},
        )
    )

    # Setup mock relationships
    mock_storage_facade.query_relationships = AsyncMock(
        return_value=[
            {"source_id": "entity-2", "target_id": "entity-1", "type": "imports"}
        ]
    )

    mock_storage_facade.query_entities = AsyncMock(
        return_value=[
            {
                "id": "entity-2",
                "name": "Entity2",
                "type": "class",
                "file_path": "agentic_inquiry/entity2.py",
            }
        ]
    )

    # Set deadline in the past to force immediate timeout
    deadline = time.time() - 1  # 1 second in the past

    # Should raise PartialResultsException with partial data
    with pytest.raises(PartialResultsException) as exc_info:
        await impact_analyzer.analyze_impact(
            entity_name="ServiceA",
            project_id="test-project",
            depth=2,
            include_indirect=True,
            deadline=deadline,
        )

    # Verify exception has partial results
    assert exc_info.value.partial_results is not None
    assert "entity_name" in exc_info.value.partial_results
    assert exc_info.value.elapsed_ms >= 0


@pytest.mark.asyncio
async def test_partial_results_exception(
    impact_analyzer, mock_entity_resolver, mock_storage_facade
):
    """Test that PartialResultsException contains expected data fields.

    Verifies AC-2.4: Exception contains partial data
    """
    import time
    from agentic_inquiry.mcp.services.impact_analyzer import PartialResultsException

    # Setup mock entity resolution
    mock_entity_resolver.resolve_entity = AsyncMock(
        return_value=EntityDefinition(
            entity_id="entity-1",
            name="ServiceA",
            entity_type="class",
            file_path="agentic_inquiry/services/a.py",
            line_start=10,
            line_end=100,
            content="class ServiceA: ...",
            docstring="Service A",
            metadata={},
        )
    )

    # Setup mock relationships
    mock_storage_facade.query_relationships = AsyncMock(return_value=[])
    mock_storage_facade.query_entities = AsyncMock(return_value=[])

    # Set deadline in the past
    deadline = time.time() - 1

    with pytest.raises(PartialResultsException) as exc_info:
        await impact_analyzer.analyze_impact(
            entity_name="ServiceA",
            project_id="test-project",
            depth=2,
            include_indirect=True,
            deadline=deadline,
        )

    # Verify exception structure
    exception = exc_info.value
    assert hasattr(exception, "partial_results")
    assert hasattr(exception, "elapsed_ms")

    # Verify partial_results has expected fields
    partial = exception.partial_results
    assert "entity_name" in partial
    assert "affected_entities" in partial
    assert "relationship_types" in partial
    assert "completed_depth" in partial
    assert "incoming_completed" in partial
    assert "outgoing_completed" in partial

    # Verify data types
    assert isinstance(partial["entity_name"], str)
    assert isinstance(partial["affected_entities"], list)
    assert isinstance(partial["relationship_types"], dict)
    assert isinstance(partial["completed_depth"], int)
    assert isinstance(partial["incoming_completed"], bool)
    assert isinstance(partial["outgoing_completed"], bool)
    assert isinstance(exception.elapsed_ms, int)


@pytest.mark.asyncio
async def test_batch_chunking_uses_config(
    impact_analyzer, mock_entity_resolver, mock_storage_facade, mock_config
):
    """Test that batch chunking uses batch_size from config.

    Verifies FR-1.6: Batch size from config
    """
    # Set a specific batch size in config
    mock_config.mcp.query.batch_size = 2  # Small batch for testing

    # Setup mock entity resolution
    mock_entity_resolver.resolve_entity = AsyncMock(
        return_value=EntityDefinition(
            entity_id="entity-1",
            name="ServiceA",
            entity_type="class",
            file_path="agentic_inquiry/services/a.py",
            line_start=10,
            line_end=100,
            content="class ServiceA: ...",
            docstring="Service A",
            metadata={},
        )
    )

    # Setup mock relationships - return 5 entities (will require 3 batches with batch_size=2)
    mock_storage_facade.query_relationships = AsyncMock(
        return_value=[
            {"source_id": f"entity-{i}", "target_id": "entity-1", "type": "imports"}
            for i in range(2, 7)  # entity-2 through entity-6 (5 entities)
        ]
    )

    # Track batch sizes in query_entities calls
    batch_sizes = []

    async def mock_query_entities(project_id, filters=None, limit=None):
        if filters and "id" in filters:
            filter_value = filters["id"]
            if isinstance(filter_value, tuple) and filter_value[0] == "IN":
                # Record the batch size
                entity_ids = filter_value[1]
                batch_sizes.append(len(entity_ids))
                return [
                    {
                        "id": eid,
                        "name": f"Entity{eid[-1]}",
                        "type": "class",
                        "file_path": f"agentic_inquiry/entity{eid[-1]}.py",
                    }
                    for eid in entity_ids
                ]
        return []

    mock_storage_facade.query_entities = mock_query_entities

    # Run impact analysis
    await impact_analyzer.analyze_impact(
        entity_name="ServiceA",
        project_id="test-project",
        depth=1,
        include_indirect=True,
    )

    # Verify batching occurred with configured batch_size
    assert len(batch_sizes) > 0, "Should have made batched queries"

    # With 5 entities and batch_size=2, expect batches of [2, 2, 1]
    assert max(batch_sizes) <= 2, (
        f"Batch sizes should not exceed configured batch_size=2, got {batch_sizes}"
    )


@pytest.mark.asyncio
async def test_batch_size_validation():
    """Test that batch_size config validation works correctly.

    Verifies AC-4.2: Batch size range validation (10-500)
    """
    from agentic_inquiry.config import MCPQueryConfig
    from agentic_inquiry.exceptions import ConfigurationError

    # Valid batch sizes should work
    valid_config = MCPQueryConfig(batch_size=100)
    assert valid_config.batch_size == 100

    # Batch size below 10 should raise error
    with pytest.raises(ConfigurationError) as exc_info:
        MCPQueryConfig(batch_size=5)
    assert "batch_size must be between 10 and 500" in str(exc_info.value)

    # Batch size above 500 should raise error
    with pytest.raises(ConfigurationError) as exc_info:
        MCPQueryConfig(batch_size=600)
    assert "batch_size must be between 10 and 500" in str(exc_info.value)

    # Boundary values should work
    edge_low = MCPQueryConfig(batch_size=10)
    assert edge_low.batch_size == 10

    edge_high = MCPQueryConfig(batch_size=500)
    assert edge_high.batch_size == 500


@pytest.mark.asyncio
async def test_traversal_limit_affects_analyze_impact(
    impact_analyzer, mock_entity_resolver, mock_storage_facade, mock_config
):
    """Test that traversal_limit config affects relationship traversal.

    Verifies AC-4.2: traversal_limit config affects behavior
    """
    # Set a low traversal limit in config
    mock_config.mcp.query.traversal_limit = 2  # Only return 2 relationships per query

    # Setup mock entity resolution
    mock_entity_resolver.resolve_entity = AsyncMock(
        return_value=EntityDefinition(
            entity_id="entity-1",
            name="ServiceA",
            entity_type="class",
            file_path="agentic_inquiry/services/a.py",
            line_start=10,
            line_end=100,
            content="class ServiceA: ...",
            docstring="Service A",
            metadata={},
        )
    )

    # Track limit parameter in query_relationships calls
    relationship_limits = []

    async def mock_query_relationships(project_id, filters=None, limit=None):
        relationship_limits.append(limit)
        # Return mock relationships (though limit will constrain in real impl)
        if "target_id" in filters and filters["target_id"] == "entity-1":
            return [
                {"source_id": "entity-2", "target_id": "entity-1", "type": "imports"},
                {"source_id": "entity-3", "target_id": "entity-1", "type": "imports"},
            ]
        return []

    mock_storage_facade.query_relationships = mock_query_relationships

    async def mock_query_entities(project_id, filters=None, limit=None):
        if filters and "id" in filters:
            filter_value = filters["id"]
            if isinstance(filter_value, tuple) and filter_value[0] == "IN":
                entity_ids = filter_value[1]
                return [
                    {
                        "id": eid,
                        "name": f"Entity{eid[-1]}",
                        "type": "class",
                        "file_path": f"agentic_inquiry/entity{eid[-1]}.py",
                    }
                    for eid in entity_ids
                ]
        return []

    mock_storage_facade.query_entities = mock_query_entities

    # Run impact analysis
    await impact_analyzer.analyze_impact(
        entity_name="ServiceA",
        project_id="test-project",
        depth=1,
        include_indirect=True,
    )

    # Verify that query_relationships was called with the configured limit
    assert len(relationship_limits) > 0, "query_relationships should have been called"

    # analyze_impact calls both traverse_relationships (uses traversal_limit=2)
    # and build_dependency_tree (uses tree_limit=50 from mock_config)
    # Verify that traversal_limit is being used for at least some calls
    has_traversal_limit = any(limit == 2 for limit in relationship_limits)
    assert has_traversal_limit, (
        f"Should use configured traversal_limit=2 for traversal, got {relationship_limits}"
    )
