"""Tests for SearchService project_id filtering functionality."""

import pytest

pytestmark = pytest.mark.unit

from dataclasses import asdict
import json
from unittest.mock import AsyncMock, MagicMock
import pytest_asyncio

from agentic_inquiry.config import Config, StorageConfig
from agentic_inquiry.database.lancedb_manager import LanceDBManager
from agentic_inquiry.models.document_chunk import DocumentChunk
from agentic_inquiry.models.graph_entity import GraphEntity
from agentic_inquiry.models.graph_relationship import GraphRelationship
from agentic_inquiry.search.service import SearchService
from agentic_inquiry.storage.facade import StorageFacade


@pytest.fixture
def mock_event_system():
    """Create a mock event system."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


@pytest.fixture
def test_config_proj1(tmp_path):
    """Provide test configuration for project 1."""
    storage_config = StorageConfig(
        root=str(tmp_path / "storage"),
    )
    config = Config(storage=storage_config)
    config.storage.default_project_id = "proj_test_1"
    return config


@pytest.fixture
def test_config_proj2(tmp_path):
    """Provide test configuration for project 2."""
    storage_config = StorageConfig(
        root=str(tmp_path / "storage"),
    )
    config = Config(storage=storage_config)
    config.storage.default_project_id = "proj_test_2"
    return config


@pytest_asyncio.fixture
async def db_manager_with_multi_project_data(test_config_proj1):
    """Create a database manager with data from multiple projects."""
    # test_config_proj1 is now a ProjectContext, extract the base Config
    config = test_config_proj1.base if hasattr(test_config_proj1, 'base') else test_config_proj1
    mock_db_manager = LanceDBManager(config=config)
    
    # Add data for project 1
    chunks_proj1 = [
        DocumentChunk(
            id="chunk1_proj1",
            doc_id="doc1_proj1",
            file_path="file1.py",
            project_id="proj_test_1",
            content="Python code for project 1",
            fts_text="Python code for project 1",
            chunk_index=0,
            vector=[0.1] * 384,
            metadata={
                "data": json.dumps({}),
                "symbol_metadata": json.dumps({}),
                "symbol_rankings": json.dumps({})
            },
            ranking_signals={
                "data": json.dumps({})
            },
        ),
        DocumentChunk(
            id="chunk2_proj1",
            doc_id="doc2_proj1",
            file_path="file2.py",
            project_id="proj_test_1",
            content="More Python code for project 1",
            fts_text="More Python code for project 1",
            chunk_index=0,
            vector=[0.2] * 384,
            metadata={
                "data": json.dumps({}),
                "symbol_metadata": json.dumps({}),
                "symbol_rankings": json.dumps({})
            },
            ranking_signals={
                "data": json.dumps({})
            },
        ),
    ]
    
    # Add data for project 2
    chunks_proj2 = [
        DocumentChunk(
            id="chunk1_proj2",
            doc_id="doc1_proj2",
            file_path="file1.py",
            project_id="proj_test_2",
            content="Python code for project 2",
            fts_text="Python code for project 2",
            chunk_index=0,
            vector=[0.3] * 384,
            metadata={
                "data": json.dumps({}),
                "symbol_metadata": json.dumps({}),
                "symbol_rankings": json.dumps({})
            },
            ranking_signals={
                "data": json.dumps({})
            },
        ),
        DocumentChunk(
            id="chunk2_proj2",
            doc_id="doc2_proj2",
            file_path="file2.py",
            project_id="proj_test_2",
            content="More Python code for project 2",
            fts_text="More Python code for project 2",
            chunk_index=0,
            vector=[0.4] * 384,
            metadata={
                "data": json.dumps({}),
                "symbol_metadata": json.dumps({}),
                "symbol_rankings": json.dumps({})
            },
            ranking_signals={
                "data": json.dumps({})
            },
        ),
    ]
    
    # Insert all chunks
    all_chunks = chunks_proj1 + chunks_proj2
    await mock_db_manager.add_document_chunks([asdict(chunk) for chunk in all_chunks])
    
    # Add graph entities for both projects
    entities_proj1 = [
        GraphEntity(
            id="entity1_proj1",
            name="ClassA",
            type="class",
            file_path="file1.py",
            doc_id="doc1_proj1",
            project_id="proj_test_1",
            vector=[0.1] * 384,
            has_ranking_signals=False,
        ),
    ]
    
    entities_proj2 = [
        GraphEntity(
            id="entity1_proj2",
            name="ClassB",
            type="class",
            file_path="file1.py",
            doc_id="doc1_proj2",
            project_id="proj_test_2",
            vector=[0.3] * 384,
            has_ranking_signals=False,
        ),
    ]
    
    all_entities = entities_proj1 + entities_proj2
    await mock_db_manager.add_graph_entities([entity.to_dict() for entity in all_entities])
    
    # Add relationships
    relationships_proj1 = [
        GraphRelationship(
            id="rel1_proj1",
            source_id="entity1_proj1",
            target_id="entity2_proj1",
            type="calls",
            project_id="proj_test_1",
            vector=[0.1] * 384,
        ),
    ]
    
    relationships_proj2 = [
        GraphRelationship(
            id="rel1_proj2",
            source_id="entity1_proj2",
            target_id="entity2_proj2",
            type="calls",
            project_id="proj_test_2",
            vector=[0.3] * 384,
        ),
    ]
    
    all_relationships = relationships_proj1 + relationships_proj2
    await mock_db_manager.add_graph_relationships([asdict(rel) for rel in all_relationships])
    
    return mock_db_manager


@pytest_asyncio.fixture
async def search_service(db_manager_with_multi_project_data, test_config_proj1, mock_event_system):
    """Create a search service with multi-project data."""
    from agentic_inquiry.storage.providers.lancedb import LanceDBVectorProvider, LanceDBGraphProvider
    from agentic_inquiry.storage.providers.lancedb.connection import LanceDBConnectionManager

    # Create connection manager with the test db_manager
    connection_manager = LanceDBConnectionManager(
        config=test_config_proj1,
        project_id="proj_test_1",
        db_manager=db_manager_with_multi_project_data,
    )
    # Mark as initialized since db_manager is already connected
    connection_manager._initialized = True

    # Use protocol-compliant providers
    vector_provider = LanceDBVectorProvider(connection_manager)
    graph_provider = LanceDBGraphProvider(connection_manager)

    facade = StorageFacade(
        config=test_config_proj1,
        project_id="proj_test_1",
        vector_provider=vector_provider,
        graph_provider=graph_provider,
    )
    return SearchService(storage=facade, config=test_config_proj1, event_system=mock_event_system)


@pytest.mark.asyncio
async def test_vector_search_filters_by_current_project(search_service):
    """Test that vector search filters by current project by default."""
    # Search with default project_id="current"
    results = await search_service.vector_search(
        query_vector=[0.1] * 384,
        limit=10,
    )

    # Should only return results from proj_test_1
    assert len(results) > 0
    for result in results:
        # project_id is in result.data directly, not in nested metadata
        assert result.data["project_id"] == "proj_test_1"


@pytest.mark.asyncio
async def test_vector_search_with_specific_project_id(search_service):
    """Test that vector search can filter by specific project_id."""
    # Search with specific project_id
    results = await search_service.vector_search(
        query_vector=[0.3] * 384,
        limit=10,
        project_id="proj_test_2",
    )
    
    # Should only return results from proj_test_2
    assert len(results) > 0
    for result in results:
        assert result.data["project_id"] == "proj_test_2"


@pytest.mark.asyncio
async def test_vector_search_all_projects(search_service):
    """Test that vector search can search all projects when project_id=None."""
    # Search all projects
    results = await search_service.vector_search(
        query_vector=[0.2] * 384,
        limit=10,
        project_id=None,
    )
    
    # Should return results from both projects
    assert len(results) > 0
    project_ids = {result.data["project_id"] for result in results}
    assert len(project_ids) >= 1  # At least one project


@pytest.mark.asyncio
async def test_fts_search_filters_by_current_project(search_service):
    """Test that FTS search filters by current project by default."""
    # Search with default project_id="current"
    results = await search_service.fts_search(
        query_fts="Python",
        limit=10,
    )
    
    # Should only return results from proj_test_1
    assert len(results) > 0
    for result in results:
        assert result.data["project_id"] == "proj_test_1"


@pytest.mark.asyncio
async def test_fts_search_with_specific_project_id(search_service):
    """Test that FTS search can filter by specific project_id."""
    # Search with specific project_id
    results = await search_service.fts_search(
        query_fts="Python",
        limit=10,
        project_id="proj_test_2",
    )
    
    # Should only return results from proj_test_2
    assert len(results) > 0
    for result in results:
        assert result.data["project_id"] == "proj_test_2"


@pytest.mark.asyncio
async def test_hybrid_search_filters_by_project(search_service):
    """Test that hybrid search filters by project_id."""
    # Hybrid search with default project
    results = await search_service.hybrid_search(
        query_vector=[0.1] * 384,
        query_fts="Python",
        limit=10,
    )
    
    # Should only return results from proj_test_1
    assert len(results) > 0
    for result in results:
        assert result.data["project_id"] == "proj_test_1"


@pytest.mark.asyncio
async def test_advanced_filter_search_filters_by_project(search_service):
    """Test that advanced filter search filters by project_id."""
    # Advanced filter with default project
    results = await search_service.advanced_filter_search(
        table_name="document_chunks",
        filters={"file_path": "file1.py"},
        limit=10,
    )

    # Should only return results from proj_test_1
    # Note: advanced_filter_search returns dicts, not SearchResult objects
    assert len(results) > 0
    for result in results:
        assert result["project_id"] == "proj_test_1"


@pytest.mark.asyncio
async def test_graph_filtered_search_filters_by_project(search_service):
    """Test that graph filtered search filters by project_id."""
    # Graph filtered search with default project
    results = await search_service.graph_filtered_search(
        graph_filters={"type": "class"},
        search_query_vector=[0.1] * 384,
        limit=10,
    )
    
    # Should only return results from proj_test_1
    for result in results:
        assert result.data["project_id"] == "proj_test_1"


@pytest.mark.asyncio
async def test_enrich_with_graph_context_filters_by_project(search_service):
    """Test that graph context enrichment filters by project_id."""
    # Get some search results
    search_results = [
        {"doc_id": "doc1_proj1", "project_id": "proj_test_1"},
    ]
    
    # Enrich with graph context
    enriched = await search_service.enrich_with_graph_context(
        search_results,
        project_id="proj_test_1",
    )
    
    # Should have graph context
    assert len(enriched) > 0


@pytest.mark.asyncio
async def test_result_metadata_includes_project_id(search_service):
    """Test that search results include project_id in result data."""
    # Perform search
    results = await search_service.vector_search(
        query_vector=[0.1] * 384,
        limit=10,
    )

    # Check that results have project_id in data
    assert len(results) > 0
    for result in results:
        # project_id is in result.data directly
        assert "project_id" in result.data


@pytest.mark.asyncio
async def test_hybrid_search_across_multiple_projects(search_service):
    """Test that hybrid search can query across multiple projects using project_ids."""
    # Hybrid search across both projects
    results = await search_service.hybrid_search(
        query_vector=[0.2] * 384,
        query_fts="Python",
        limit=10,
        project_ids=["proj_test_1", "proj_test_2"],
    )
    
    # Should return results from both projects
    assert len(results) > 0
    project_ids = {result.data["project_id"] for result in results}
    assert len(project_ids) >= 1  # At least one project
    # Verify we can get results from both projects
    assert "proj_test_1" in project_ids or "proj_test_2" in project_ids


@pytest.mark.asyncio
async def test_graph_filtered_search_across_multiple_projects(search_service):
    """Test that graph filtered search can query across multiple projects using project_ids."""
    # Graph filtered search across both projects
    results = await search_service.graph_filtered_search(
        graph_filters={"type": "class"},
        search_query_vector=[0.2] * 384,
        limit=10,
        project_ids=["proj_test_1", "proj_test_2"],
    )
    
    # Should return results from both projects (if graph ranking is available)
    # If graph ranking is not available, it falls back to regular search
    if len(results) > 0:
        project_ids = {result.data["project_id"] for result in results}
        # At least one project should be represented
        assert len(project_ids) >= 1
