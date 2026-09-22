"""Tests for SearchService extensions: resolve_entity and traverse_relationships."""

import pytest

pytestmark = pytest.mark.unit

import json
from unittest.mock import AsyncMock, MagicMock
import pytest_asyncio

from agent_vault.config import Config, StorageConfig
from agent_vault.database.adapters.lancedb_adapter import LanceDBAdapter
from agent_vault.database.lancedb_manager import LanceDBManager
from agent_vault.models.graph_entity import GraphEntity, EntityType
from agent_vault.models.graph_relationship import GraphRelationship, RelationshipType
from agent_vault.search.service import SearchService


@pytest.fixture
def mock_event_system():
    """Create a mock event system."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


@pytest.fixture
def mock_config(tmp_path):
    """Provide test configuration."""
    storage_config = StorageConfig(
        root=str(tmp_path / "storage"),
    )
    config = Config(storage=storage_config)
    config.storage.default_project_id = "test_project"
    return config


@pytest_asyncio.fixture
async def db_manager_with_graph_data(mock_config):
    """Create a database manager with graph entities and relationships."""
    # Extract base config from ProjectContext
    config = mock_config.base if hasattr(mock_config, 'base') else mock_config
    db_manager = LanceDBManager(config=config)

    # Create test entities
    entities = [
        GraphEntity(
            id="entity_1",
            name="PaymentProcessor",
            type=EntityType.CODE_CLASS.value,
            file_path="payment/processor.py",
            doc_id="doc_1",
            project_id="test_project",
            vector=[0.1] * 384,
            pagerank=0.8,
        ),
        GraphEntity(
            id="entity_2",
            name="PaymentProcessor.process",
            type=EntityType.CODE_FUNCTION.value,
            file_path="payment/processor.py",
            doc_id="doc_2",
            project_id="test_project",
            vector=[0.2] * 384,
            pagerank=0.6,
        ),
        GraphEntity(
            id="entity_3",
            name="OrderProcessor.process",
            type=EntityType.CODE_FUNCTION.value,
            file_path="order/processor.py",
            doc_id="doc_3",
            project_id="test_project",
            vector=[0.3] * 384,
            pagerank=0.4,
        ),
        GraphEntity(
            id="entity_4",
            name="validate_payment",
            type=EntityType.CODE_FUNCTION.value,
            file_path="payment/validator.py",
            doc_id="doc_4",
            project_id="test_project",
            vector=[0.15] * 384,
            pagerank=0.5,
        ),
        GraphEntity(
            id="entity_5",
            name="PaymentGateway",
            type=EntityType.CODE_CLASS.value,
            file_path="payment/gateway.py",
            doc_id="doc_5",
            project_id="test_project",
            vector=[0.12] * 384,
            pagerank=0.7,
        ),
    ]

    # Create test relationships
    relationships = [
        GraphRelationship(
            id="rel_1",
            source_id="entity_2",
            target_id="entity_4",
            type=RelationshipType.CALLS.value,
            project_id="test_project",
            vector=[0.1] * 384,
            metadata=json.dumps({"line_number": 42, "file_path": "payment/processor.py"}),
        ),
        GraphRelationship(
            id="rel_2",
            source_id="entity_2",
            target_id="entity_5",
            type=RelationshipType.USES.value,
            project_id="test_project",
            vector=[0.2] * 384,
        ),
        GraphRelationship(
            id="rel_3",
            source_id="entity_1",
            target_id="entity_2",
            type=RelationshipType.DEFINES.value,
            project_id="test_project",
            vector=[0.3] * 384,
        ),
        GraphRelationship(
            id="rel_4",
            source_id="entity_4",
            target_id="entity_5",
            type=RelationshipType.CALLS.value,
            project_id="test_project",
            vector=[0.4] * 384,
        ),
    ]

    # Insert entities
    await db_manager.add_graph_entities(entities)

    # Insert relationships
    await db_manager.add_graph_relationships(relationships)

    yield db_manager

    # Cleanup
    await db_manager.close()


@pytest.fixture
def mock_storage_facade(db_manager_with_graph_data):
    """Create a mock StorageFacade that wraps the real db_manager.

    SearchService expects StorageFacade with:
    - vector_provider: LanceDBAdapter wrapping the db_manager
    - project_id: "test_project"
    """
    # Create adapter wrapping the real db_manager
    adapter = LanceDBAdapter(db_manager_with_graph_data)
    db_manager = db_manager_with_graph_data

    # Create mock StorageFacade
    mock_storage = MagicMock()
    mock_storage.vector_provider = adapter
    mock_storage.project_id = "test_project"

    # Add async methods that GraphSearchService now uses directly
    # These delegate to the real db_manager for query operations
    async def query_raw(table_name, filters=None, limit=None, project_id=None):
        return await adapter.query_raw(
            table=table_name,
            filters=filters,
            limit=limit,
            project_id=project_id or "test_project",
        )

    async def list_tables():
        return await db_manager.list_tables()

    async def vector_search_raw(table, vector, vector_column="vector", limit=10, filters=None, project_id=None):
        return await adapter.vector_search_raw(
            table=table,
            vector=vector,
            vector_column=vector_column,
            limit=limit,
            filters=filters,
            project_id=project_id or "test_project",
        )

    async def query_across_projects(table_name, project_ids, filters=None, limit=None):
        return await adapter.query_across_projects(
            table_name=table_name,
            project_ids=project_ids,
            filters=filters,
            limit=limit,
        )

    mock_storage.query_raw = query_raw
    mock_storage.list_tables = list_tables
    mock_storage.vector_search_raw = vector_search_raw
    mock_storage.query_across_projects = query_across_projects

    return mock_storage


@pytest.mark.asyncio
async def test_resolve_entity_exact_match(mock_storage_facade, mock_config, mock_event_system):
    """test_resolve_entity_exact_match"""
    search_service = SearchService(
        storage=mock_storage_facade,
        config=mock_config,
        event_system=mock_event_system,
    )
    
    result = await search_service.resolve_entity(
        entity_name="PaymentProcessor",
        project_id="test_project",
    )
    
    assert result["found"] is True
    assert result["disambiguation_needed"] is False
    assert len(result["matches"]) == 1
    assert result["matches"][0]["name"] == "PaymentProcessor"
    assert result["matches"][0]["type"] == EntityType.CODE_CLASS.value


@pytest.mark.asyncio
async def test_resolve_entity_qualified_name(mock_storage_facade, mock_config, mock_event_system):
    """test_resolve_entity_qualified_name"""
    search_service = SearchService(
        storage=mock_storage_facade,
        config=mock_config,
        event_system=mock_event_system,
    )
    
    result = await search_service.resolve_entity(
        entity_name="PaymentProcessor.process",
        project_id="test_project",
    )
    
    assert result["found"] is True
    assert len(result["matches"]) == 1
    assert result["matches"][0]["name"] == "PaymentProcessor.process"


@pytest.mark.asyncio
async def test_resolve_entity_disambiguation_needed(mock_storage_facade, mock_config, mock_event_system):
    """test_resolve_entity_disambiguation_needed"""
    search_service = SearchService(
        storage=mock_storage_facade,
        config=mock_config,
        event_system=mock_event_system,
    )
    
    result = await search_service.resolve_entity(
        entity_name="process",
        project_id="test_project",
    )
    
    assert result["found"] is True
    assert result["disambiguation_needed"] is True
    assert len(result["matches"]) == 2  # PaymentProcessor.process and OrderProcessor.process
    
    # Check that matches are sorted by usage score (pagerank)
    assert result["matches"][0]["usage_score"] >= result["matches"][1]["usage_score"]


@pytest.mark.asyncio
async def test_resolve_entity_with_type_filter(mock_storage_facade, mock_config, mock_event_system):
    """test_resolve_entity_with_type_filter"""
    search_service = SearchService(
        storage=mock_storage_facade,
        config=mock_config,
        event_system=mock_event_system,
    )
    
    result = await search_service.resolve_entity(
        entity_name="process",
        entity_type=EntityType.CODE_FUNCTION.value,
        project_id="test_project",
    )
    
    assert result["found"] is True
    assert len(result["matches"]) == 2
    # All matches should be functions
    for match in result["matches"]:
        assert match["type"] == EntityType.CODE_FUNCTION.value


@pytest.mark.asyncio
async def test_resolve_entity_not_found(mock_storage_facade, mock_config, mock_event_system):
    """test_resolve_entity_not_found"""
    search_service = SearchService(
        storage=mock_storage_facade,
        config=mock_config,
        event_system=mock_event_system,
    )
    
    result = await search_service.resolve_entity(
        entity_name="NonExistentEntity",
        project_id="test_project",
        similarity_threshold=0.5,
    )
    
    assert result["found"] is False
    assert len(result["matches"]) == 0
    # Should have suggestions based on similarity
    # (actual suggestions depend on embeddings, so we just check structure)
    assert "suggestions" in result


@pytest.mark.asyncio
async def test_traverse_relationships_outgoing(mock_storage_facade, mock_config, mock_event_system):
    """test_traverse_relationships_outgoing"""
    search_service = SearchService(
        storage=mock_storage_facade,
        config=mock_config,
        event_system=mock_event_system,
    )
    
    result = await search_service.traverse_relationships(
        entity_id="entity_2",  # PaymentProcessor.process
        direction="outgoing",
        max_depth=1,
        project_id="test_project",
    )
    
    assert result["entity"]["id"] == "entity_2"
    assert result["depth_reached"] == 1
    assert len(result["relationships"]) == 2  # calls validate_payment, uses PaymentGateway
    
    # Check relationship details
    for rel in result["relationships"]:
        assert rel["source_id"] == "entity_2"
        assert rel["direction"] == "outgoing"
        assert rel["depth"] == 1
        assert "source_name" in rel
        assert "target_name" in rel


@pytest.mark.asyncio
async def test_traverse_relationships_incoming(mock_storage_facade, mock_config, mock_event_system):
    """test_traverse_relationships_incoming"""
    search_service = SearchService(
        storage=mock_storage_facade,
        config=mock_config,
        event_system=mock_event_system,
    )
    
    result = await search_service.traverse_relationships(
        entity_id="entity_2",  # PaymentProcessor.process
        direction="incoming",
        max_depth=1,
        project_id="test_project",
    )
    
    assert result["entity"]["id"] == "entity_2"
    assert len(result["relationships"]) == 1  # defined by PaymentProcessor
    
    for rel in result["relationships"]:
        assert rel["target_id"] == "entity_2"
        assert rel["direction"] == "incoming"


@pytest.mark.asyncio
async def test_traverse_relationships_both_directions(mock_storage_facade, mock_config, mock_event_system):
    """test_traverse_relationships_both_directions"""
    search_service = SearchService(
        storage=mock_storage_facade,
        config=mock_config,
        event_system=mock_event_system,
    )
    
    result = await search_service.traverse_relationships(
        entity_id="entity_2",
        direction="both",
        max_depth=1,
        project_id="test_project",
    )
    
    assert result["entity"]["id"] == "entity_2"
    # Should have both incoming and outgoing relationships
    assert len(result["relationships"]) == 3  # 2 outgoing + 1 incoming
    
    directions = {rel["direction"] for rel in result["relationships"]}
    assert "outgoing" in directions
    assert "incoming" in directions


@pytest.mark.asyncio
async def test_traverse_relationships_with_depth(mock_storage_facade, mock_config, mock_event_system):
    """test_traverse_relationships_with_depth"""
    search_service = SearchService(
        storage=mock_storage_facade,
        config=mock_config,
        event_system=mock_event_system,
    )
    
    result = await search_service.traverse_relationships(
        entity_id="entity_2",  # PaymentProcessor.process
        direction="outgoing",
        max_depth=2,
        project_id="test_project",
    )
    
    assert result["entity"]["id"] == "entity_2"
    # Should traverse: entity_2 -> entity_4 -> entity_5 (depth 2)
    # and entity_2 -> entity_5 (depth 1)
    assert result["depth_reached"] >= 1
    
    # Check that we have relationships at different depths
    depths = {rel["depth"] for rel in result["relationships"]}
    assert 1 in depths


@pytest.mark.asyncio
async def test_traverse_relationships_with_type_filter(mock_storage_facade, mock_config, mock_event_system):
    """test_traverse_relationships_with_type_filter"""
    search_service = SearchService(
        storage=mock_storage_facade,
        config=mock_config,
        event_system=mock_event_system,
    )
    
    result = await search_service.traverse_relationships(
        entity_id="entity_2",
        relationship_types=[RelationshipType.CALLS.value],
        direction="outgoing",
        max_depth=1,
        project_id="test_project",
    )
    
    assert result["entity"]["id"] == "entity_2"
    # Should only have CALLS relationships
    assert len(result["relationships"]) == 1
    assert result["relationships"][0]["type"] == RelationshipType.CALLS.value


@pytest.mark.asyncio
async def test_traverse_relationships_with_metadata(mock_storage_facade, mock_config, mock_event_system):
    """test_traverse_relationships_with_metadata"""
    search_service = SearchService(
        storage=mock_storage_facade,
        config=mock_config,
        event_system=mock_event_system,
    )
    
    result = await search_service.traverse_relationships(
        entity_id="entity_2",
        direction="outgoing",
        max_depth=1,
        include_metadata=True,
        project_id="test_project",
    )
    
    # Find the relationship with metadata
    rel_with_metadata = [r for r in result["relationships"] if r.get("metadata")]
    assert len(rel_with_metadata) > 0
    
    # Check metadata structure
    metadata = json.loads(rel_with_metadata[0]["metadata"])
    assert "line_number" in metadata


@pytest.mark.asyncio
async def test_traverse_relationships_entity_not_found(mock_storage_facade, mock_config, mock_event_system):
    """test_traverse_relationships_entity_not_found"""
    search_service = SearchService(
        storage=mock_storage_facade,
        config=mock_config,
        event_system=mock_event_system,
    )
    
    result = await search_service.traverse_relationships(
        entity_id="nonexistent_entity",
        direction="outgoing",
        max_depth=1,
        project_id="test_project",
    )
    
    assert result["entity"] is None
    assert "error" in result
    assert len(result["relationships"]) == 0


@pytest.mark.asyncio
async def test_traverse_relationships_invalid_direction(mock_storage_facade, mock_config, mock_event_system):
    """test_traverse_relationships_invalid_direction"""
    search_service = SearchService(
        storage=mock_storage_facade,
        config=mock_config,
        event_system=mock_event_system,
    )
    
    with pytest.raises(ValueError, match="Invalid direction"):
        await search_service.traverse_relationships(
            entity_id="entity_2",
            direction="invalid",
            max_depth=1,
            project_id="test_project",
        )
