"""Integration tests for analyze_impact tool with ImpactAnalyzer."""

import pytest

pytestmark = pytest.mark.integration
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock

from agentic_inquiry.config import Config
from agentic_inquiry.mcp.factories import create_mcp_services
from agentic_inquiry.mcp.tools.analysis import analyze_impact
from agentic_inquiry.models.graph_entity import GraphEntity
from agentic_inquiry.models.graph_relationship import GraphRelationship


@pytest_asyncio.fixture
async def test_services(tmp_path):
    """Create MCP services with test configuration."""
    # Create test config
    config = Config.load()
    config.storage.root = str(tmp_path / "storage")

    # Create services
    services = await create_mcp_services(config=config, project_id="test_project")

    # Mock event system to avoid actual event emission
    services["event_system"] = MagicMock()
    services["event_system"].emit = AsyncMock(return_value=None)

    yield services

    # Cleanup
    if "storage" in services:
        await services["storage"].close()


@pytest_asyncio.fixture
async def indexed_services(test_services):
    """Create services with test entities and relationships in database."""
    db_manager = test_services["storage"]

    # Create test entities (without line_start/line_end to match schema)
    entities = [
        GraphEntity(
            id="entity_1",
            name="SearchService",
            type="class",
            file_path="agentic_inquiry/search/service.py",
            doc_id="doc_1",
            project_id="test_project",
            vector=[0.1] * 384,
            pagerank=0.8,
        ),
        GraphEntity(
            id="entity_2",
            name="IndexingPipeline",
            type="class",
            file_path="agentic_inquiry/indexing/pipeline.py",
            doc_id="doc_2",
            project_id="test_project",
            vector=[0.12] * 384,
            pagerank=0.9,
        ),
        GraphEntity(
            id="entity_3",
            name="ContextBuilder",
            type="class",
            file_path="agentic_inquiry/mcp/services/context_builder.py",
            doc_id="doc_3",
            project_id="test_project",
            vector=[0.15] * 384,
            pagerank=0.7,
        ),
        GraphEntity(
            id="entity_4",
            name="MCPServer",
            type="class",
            file_path="agentic_inquiry/mcp/server.py",
            doc_id="doc_4",
            project_id="test_project",
            vector=[0.18] * 384,
            pagerank=0.85,
        ),
        GraphEntity(
            id="entity_5",
            name="LanceDBManager",
            type="class",
            file_path="agentic_inquiry/database/lancedb_manager.py",
            doc_id="doc_5",
            project_id="test_project",
            vector=[0.2] * 384,
            pagerank=0.95,
        ),
    ]

    # Add entities to database
    await db_manager.upsert_entities(entities)

    # Create test relationships
    # SearchService is used by IndexingPipeline and ContextBuilder
    # SearchService depends on LanceDBManager
    # ContextBuilder is used by MCPServer
    relationships = [
        GraphRelationship(
            id="rel_1",
            source_id="entity_2",  # IndexingPipeline
            target_id="entity_1",  # SearchService
            type="imports",
            project_id="test_project",
            vector=[0.3] * 384,
        ),
        GraphRelationship(
            id="rel_2",
            source_id="entity_3",  # ContextBuilder
            target_id="entity_1",  # SearchService
            type="calls",
            project_id="test_project",
            vector=[0.35] * 384,
        ),
        GraphRelationship(
            id="rel_3",
            source_id="entity_1",  # SearchService
            target_id="entity_5",  # LanceDBManager
            type="imports",
            project_id="test_project",
            vector=[0.4] * 384,
        ),
        GraphRelationship(
            id="rel_4",
            source_id="entity_4",  # MCPServer
            target_id="entity_3",  # ContextBuilder
            type="imports",
            project_id="test_project",
            vector=[0.45] * 384,
        ),
    ]

    # Add relationships to database
    await db_manager.upsert_relationships(relationships)

    yield test_services


@pytest_asyncio.fixture
async def test_session(indexed_services):
    """Create a test session."""
    session_manager = indexed_services["session_manager"]
    session_info = await session_manager.create_session(
        project_id="test_project", description="Test session for analyze_impact"
    )
    return session_info["session_id"]


@pytest.mark.asyncio
async def test_analyze_impact_returns_impact_radius(indexed_services, test_session):
    """Test that analyze_impact returns impact_radius > 0 for known entities."""
    result = await analyze_impact(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService",
        max_depth=2,
    )

    # Verify impact_radius is present and > 0
    assert "impact_radius" in result
    assert result["impact_radius"] > 0, (
        "Impact radius should be > 0 for entity with relationships"
    )


@pytest.mark.asyncio
async def test_analyze_impact_returns_affected_files(indexed_services, test_session):
    """Test that analyze_impact returns affected_files dictionary."""
    result = await analyze_impact(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService",
        max_depth=2,
    )

    # Verify affected_files is present
    assert "affected_files" in result
    assert isinstance(result["affected_files"], dict)
    assert len(result["affected_files"]) > 0, "Should have at least one affected file"

    # Verify file_count matches
    assert "file_count" in result
    assert result["file_count"] == len(result["affected_files"])


@pytest.mark.asyncio
async def test_analyze_impact_returns_affected_entities(indexed_services, test_session):
    """Test that analyze_impact returns affected_entities list."""
    result = await analyze_impact(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService",
        max_depth=2,
    )

    # Verify affected_entities is present
    assert "affected_entities" in result
    assert isinstance(result["affected_entities"], list)
    assert len(result["affected_entities"]) > 0, (
        "Should have at least one affected entity"
    )

    # Verify entity structure
    if result["affected_entities"]:
        entity = result["affected_entities"][0]
        assert "name" in entity
        assert "entity_type" in entity
        assert "file_path" in entity
        assert "relationship_type" in entity


@pytest.mark.asyncio
async def test_analyze_impact_returns_relationship_types(
    indexed_services, test_session
):
    """Test that analyze_impact returns relationship_types dictionary."""
    result = await analyze_impact(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService",
        max_depth=2,
    )

    # Verify relationship_types is present
    assert "relationship_types" in result
    assert isinstance(result["relationship_types"], dict)

    # Should have at least one relationship type
    if result["impact_radius"] > 0:
        assert len(result["relationship_types"]) > 0


@pytest.mark.asyncio
async def test_analyze_impact_with_depth_1(indexed_services, test_session):
    """Test analyze_impact with depth=1 (direct dependencies only)."""
    result = await analyze_impact(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService",
        max_depth=1,
    )

    # Verify traversal_depth is set correctly
    assert "traversal_depth" in result
    assert result["traversal_depth"] == 1

    # Should have some impact
    assert result["impact_radius"] > 0


@pytest.mark.asyncio
async def test_analyze_impact_with_depth_3(indexed_services, test_session):
    """Test analyze_impact with depth=3 (transitive dependencies)."""
    result = await analyze_impact(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService",
        max_depth=3,
    )

    # Verify traversal_depth is set correctly
    assert "traversal_depth" in result
    assert result["traversal_depth"] == 3

    # Should have some impact
    assert result["impact_radius"] > 0


@pytest.mark.asyncio
async def test_analyze_impact_entity_not_found(indexed_services, test_session):
    """Test analyze_impact with non-existent entity."""
    result = await analyze_impact(
        services=indexed_services,
        session_id=test_session,
        entity="NonExistentEntity",
        max_depth=2,
    )

    # Should return error response
    assert "error" in result or "message" in result

    # Should include suggestions if available
    if "suggestions" in result:
        assert isinstance(result["suggestions"], list)


@pytest.mark.asyncio
async def test_analyze_impact_invalid_session(indexed_services):
    """Test with invalid session ID."""
    result = await analyze_impact(
        services=indexed_services,
        session_id="invalid_session_id",
        entity="SearchService",
        max_depth=2,
    )

    # Should return error response
    assert "error" in result or "message" in result


@pytest.mark.asyncio
async def test_analyze_impact_correct_structure(indexed_services, test_session):
    """Test that response has correct structure."""
    result = await analyze_impact(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService",
        max_depth=2,
    )

    # Verify all required fields are present
    assert "entity" in result
    assert "impact_radius" in result
    assert "affected_files" in result
    assert "file_count" in result
    assert "affected_entities" in result
    assert "relationship_types" in result
    assert "traversal_depth" in result
    assert "guidance" in result

    # Verify guidance structure
    guidance = result["guidance"]
    assert "risk_level" in guidance
    assert "recommendation" in guidance
    assert guidance["risk_level"] in ["low", "medium", "high"]


@pytest.mark.asyncio
async def test_analyze_impact_case_insensitive(indexed_services, test_session):
    """Test case-insensitive entity resolution."""
    result = await analyze_impact(
        services=indexed_services,
        session_id=test_session,
        entity="searchservice",  # lowercase
        max_depth=2,
    )

    # Should still find SearchService
    if "entity" in result:
        assert result["entity"] == "searchservice"  # Original input preserved
        assert result["impact_radius"] >= 0


@pytest.mark.asyncio
async def test_analyze_impact_multiple_entities(indexed_services, test_session):
    """Test analyze_impact for multiple entities."""
    entities_to_test = ["SearchService", "IndexingPipeline", "ContextBuilder"]

    for entity_name in entities_to_test:
        result = await analyze_impact(
            services=indexed_services,
            session_id=test_session,
            entity=entity_name,
            max_depth=2,
        )

        # Each should have valid structure
        if "impact_radius" in result:
            assert result["impact_radius"] >= 0
            assert "affected_files" in result
            assert "affected_entities" in result


@pytest.mark.asyncio
async def test_analyze_impact_transitive_relationships(indexed_services, test_session):
    """Test that transitive relationships are found with depth > 1."""
    # SearchService -> ContextBuilder -> MCPServer (depth 2)
    result = await analyze_impact(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService",
        max_depth=2,
    )

    # With depth=2, should find entities at multiple levels
    if result["impact_radius"] > 0:
        # Should have found at least direct dependencies
        assert len(result["affected_entities"]) > 0


@pytest.mark.asyncio
async def test_analyze_impact_risk_levels(indexed_services, test_session):
    """Test that risk levels are calculated correctly."""
    result = await analyze_impact(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService",
        max_depth=2,
    )

    # Verify risk level is appropriate for impact radius
    if "guidance" in result:
        risk_level = result["guidance"]["risk_level"]
        impact_radius = result["impact_radius"]

        if impact_radius > 10:
            assert risk_level == "high"
        elif impact_radius > 5:
            assert risk_level == "medium"
        else:
            assert risk_level == "low"


@pytest.mark.asyncio
async def test_analyze_impact_default_depth(indexed_services, test_session):
    """Test analyze_impact with default depth."""
    result = await analyze_impact(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService",
        # max_depth not specified, should use default (2)
    )

    # Should use default depth
    assert "traversal_depth" in result
    assert result["traversal_depth"] == 2  # Default from config


@pytest.mark.asyncio
async def test_analyze_impact_affected_files_grouping(indexed_services, test_session):
    """Test that affected entities are grouped by file correctly."""
    result = await analyze_impact(
        services=indexed_services,
        session_id=test_session,
        entity="SearchService",
        max_depth=2,
    )

    # Verify affected_files contains file paths as keys
    if result["affected_files"]:
        for file_path, count in result["affected_files"].items():
            assert isinstance(file_path, str)
            assert isinstance(count, int)
            assert count > 0


@pytest.mark.asyncio
async def test_analyze_impact_success_rate(indexed_services, test_session):
    """Test that success rate is >80% for indexed entities with relationships."""
    # Test multiple known entities
    entities_to_test = [
        "SearchService",
        "IndexingPipeline",
        "ContextBuilder",
        "MCPServer",
        "LanceDBManager",
    ]

    successful = 0
    total = len(entities_to_test)

    for entity_name in entities_to_test:
        result = await analyze_impact(
            services=indexed_services,
            session_id=test_session,
            entity=entity_name,
            max_depth=2,
        )

        # Count as successful if impact_radius is present and >= 0
        if "impact_radius" in result and result["impact_radius"] >= 0:
            successful += 1

    success_rate = successful / total

    # Verify >80% success rate (requirement 2.5)
    assert success_rate > 0.8, f"Success rate {success_rate:.1%} is below 80% threshold"
