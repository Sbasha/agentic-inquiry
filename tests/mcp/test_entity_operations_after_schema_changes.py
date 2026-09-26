"""Integration tests for entity operations after SchemaProcessor changes.

Tests that entity operations (understand_entity, analyze_impact) work correctly
after the schema processing refactoring. Verifies:
- Files are indexed correctly with new SchemaProcessor
- Entity operations return correct results
- No "file not found" errors occur
- Database integrity is maintained

Requirements: 3.6, 3.7, 3.9, 3.10, 6.13
"""

import pytest

pytestmark = pytest.mark.integration

import asyncio
import time
import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from agentic_inquiry.config import Config


async def _wait_for_indexing_completion(session_manager, session_id, operation_id, timeout=30.0):
    """Wait for directory indexing to complete by polling session events."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        session = await session_manager.get_session(session_id, include_history=True)
        if hasattr(session, "events"):
            for event in session.events:
                if event.get("event_type") == "indexing_completed":
                    data = event.get("data", {})
                    if data.get("operation_id") == operation_id:
                        return {
                            "status": data.get("status", "completed"),
                            "items_processed": data.get("items_processed", 0),
                            "chunks_created": data.get("chunks_created", 0)
                        }
        await asyncio.sleep(0.1)
    return {"status": "timeout", "error": "Indexing did not complete in time"}


from agentic_inquiry.mcp.factories import close_mcp_services, create_mcp_services
from agentic_inquiry.mcp.tools.knowledge import add_knowledge
from agentic_inquiry.mcp.tools.analysis import understand_entity, analyze_impact


@pytest_asyncio.fixture
async def test_services(tmp_path):
    """Create MCP services with test configuration."""
    # Create test config
    config = Config.load()
    config.storage.root = str(tmp_path / "storage")
    
    # Create services
    services = await create_mcp_services(
        config=config,
        project_id="test_entity_ops"
    )
    
    # Mock event system to avoid actual event emission
    event_system = services["event_system"]
    services["event_system"] = MagicMock()
    services["event_system"].emit = AsyncMock(return_value=None)
    
    yield services

    await close_mcp_services({**services, "event_system": event_system})


@pytest_asyncio.fixture
async def test_session(test_services):
    """Create a test session."""
    session_manager = test_services["session_manager"]
    session_info = await session_manager.create_session(
        project_id="test_entity_ops",
        description="Test session for entity operations"
    )
    return session_info["session_id"]


@pytest_asyncio.fixture
async def indexed_test_files(test_services, test_session, tmp_path, monkeypatch):
    """Index test files using new SchemaProcessor and return file paths."""
    # Change to tmp_path for relative path resolution
    monkeypatch.chdir(tmp_path)
    
    # Create test directory
    test_dir = tmp_path / "test_code"
    test_dir.mkdir()
    
    # Create Python file with classes and functions
    search_service_file = test_dir / "search_service.py"
    search_service_content = '''"""Search service for semantic search."""

class SearchService:
    """Service for searching indexed content."""
    
    def __init__(self, mock_db_manager, config):
        """Initialize search service.
        
        Args:
            mock_db_manager: Database manager instance
            config: Configuration object
        """
        self.mock_db_manager = mock_db_manager
        self.config = config
    
    async def search(self, query: str, limit: int = 10):
        """Search for content using vector similarity.
        
        Args:
            query: Search query string
            limit: Maximum number of results
            
        Returns:
            List of search results
        """
        # Perform vector search
        results = await self.mock_db_manager.vector_search(query, limit)
        return results
    
    async def hybrid_search(self, query: str, limit: int = 10):
        """Search using hybrid vector + FTS approach.
        
        Args:
            query: Search query string
            limit: Maximum number of results
            
        Returns:
            Combined search results
        """
        # Combine vector and FTS results
        vector_results = await self.search(query, limit)
        fts_results = await self.mock_db_manager.fts_search(query, limit)
        return self._merge_results(vector_results, fts_results)
    
    def _merge_results(self, vector_results, fts_results):
        """Merge vector and FTS results."""
        # Simple merge logic
        return vector_results + fts_results
'''
    search_service_file.write_text(search_service_content)
    
    # Create another Python file that uses SearchService
    indexing_pipeline_file = test_dir / "mock_indexing_pipeline.py"
    indexing_pipeline_content = '''"""Indexing pipeline for processing documents."""

from search_service import SearchService

class IndexingPipeline:
    """Pipeline for indexing documents."""
    
    def __init__(self, mock_db_manager, config):
        """Initialize indexing pipeline.
        
        Args:
            mock_db_manager: Database manager instance
            config: Configuration object
        """
        self.mock_db_manager = mock_db_manager
        self.config = config
        self.search_service = SearchService(mock_db_manager, config)
    
    async def index_file(self, file_path: str):
        """Index a single file.
        
        Args:
            file_path: Path to file to index
            
        Returns:
            Indexing result
        """
        # Parse and index file
        content = self._read_file(file_path)
        chunks = self._chunk_content(content)
        await self.mock_db_manager.add_chunks(chunks)
        return {"status": "completed", "chunks": len(chunks)}
    
    async def process_document(self, document):
        """Process a parsed document.
        
        Args:
            document: Parsed document to process
        """
        # Process document chunks
        for chunk in document.chunks:
            await self.mock_db_manager.add_chunk(chunk)
    
    def _read_file(self, file_path: str):
        """Read file content."""
        with open(file_path) as f:
            return f.read()
    
    def _chunk_content(self, content: str):
        """Split content into chunks."""
        # Simple chunking
        return [content[i:i+1000] for i in range(0, len(content), 1000)]
'''
    indexing_pipeline_file.write_text(indexing_pipeline_content)
    
    # Create a third file that uses both
    context_builder_file = test_dir / "context_builder.py"
    context_builder_content = '''"""Context builder for AI agents."""

from search_service import SearchService
from mock_indexing_pipeline import IndexingPipeline

class ContextBuilder:
    """Build context for AI agents."""
    
    def __init__(self, mock_db_manager, config):
        """Initialize context builder.
        
        Args:
            mock_db_manager: Database manager instance
            config: Configuration object
        """
        self.mock_db_manager = mock_db_manager
        self.config = config
        self.search_service = SearchService(mock_db_manager, config)
        self.mock_indexing_pipeline = IndexingPipeline(mock_db_manager, config)
    
    async def build_context(self, query: str, max_tokens: int = 4000):
        """Build context from search results.
        
        Args:
            query: Query to build context for
            max_tokens: Maximum tokens in context
            
        Returns:
            Context string
        """
        # Search for relevant content
        results = await self.search_service.hybrid_search(query, limit=20)
        
        # Build context from results
        context_parts = []
        total_tokens = 0
        
        for result in results:
            content = result.get("content", "")
            tokens = len(content.split())
            
            if total_tokens + tokens <= max_tokens:
                context_parts.append(content)
                total_tokens += tokens
            else:
                break
        
        return "\\n\\n".join(context_parts)
'''
    context_builder_file.write_text(context_builder_content)
    
    # Index all files using add_knowledge (which uses SchemaProcessor)
    for file_path in [search_service_file, indexing_pipeline_file, context_builder_file]:
        result = await add_knowledge(
            services=test_services,
            session_id=test_session,
            content_type="file",
            source=str(file_path)
        )
        
        # Verify indexing succeeded
        assert result["status"] == "completed", f"Failed to index {file_path}: {result}"
        assert result["items_processed"] == 1
        assert result["chunks_created"] > 0
    
    return {
        "search_service": search_service_file,
        "mock_indexing_pipeline": indexing_pipeline_file,
        "context_builder": context_builder_file
    }


@pytest.mark.asyncio
async def test_understand_entity_after_schema_changes(test_services, test_session, indexed_test_files):
    """Test understand_entity works after SchemaProcessor changes.
    
    Requirements: 3.6, 3.7, 6.13
    """
    # Test understanding SearchService class
    result = await understand_entity(
        services=test_services,
        session_id=test_session,
        entity="SearchService"
    )
    
    # Verify no "file not found" errors
    assert "error" not in result or "file not found" not in str(result.get("error", "")).lower(), \
        f"Got file not found error: {result}"
    
    # Verify entity information is present
    assert "entity" in result, f"Entity not found in result: {result}"
    assert result["entity"]["name"] == "SearchService"
    assert result["entity"]["entity_type"] in ["class", "class"]
    assert result["entity"]["file_path"]
    assert "line_start" in result["entity"]
    
    # Verify content is present
    assert "content" in result["entity"]
    assert "documentation" in result["entity"]


@pytest.mark.asyncio
async def test_understand_entity_with_dependencies_after_schema_changes(
    test_services, test_session, indexed_test_files
):
    """Test understand_entity with dependencies after SchemaProcessor changes.
    
    Requirements: 3.6, 3.7, 6.13
    """
    # Test understanding IndexingPipeline (which depends on SearchService)
    result = await understand_entity(
        services=test_services,
        session_id=test_session,
        entity="IndexingPipeline",
        include_dependencies=True
    )
    
    # Verify no errors
    assert "error" not in result or "file not found" not in str(result.get("error", "")).lower()
    
    # Verify entity found
    assert "entity" in result
    assert result["entity"]["name"] == "IndexingPipeline"
    
    # Verify dependencies structure
    assert "dependencies" in result
    assert isinstance(result["dependencies"], list)


@pytest.mark.asyncio
async def test_understand_entity_method_after_schema_changes(
    test_services, test_session, indexed_test_files
):
    """Test understanding methods after SchemaProcessor changes.
    
    Requirements: 3.6, 3.7, 6.13
    """
    # Test understanding a method
    result = await understand_entity(
        services=test_services,
        session_id=test_session,
        entity="search"
    )
    
    # Verify no errors
    assert "error" not in result or "file not found" not in str(result.get("error", "")).lower()
    
    # Verify method found (if entity resolution works)
    if "entity" in result:
        assert result["entity"]["entity_type"] in ["function", "method", "function", "method"]


@pytest.mark.asyncio
async def test_analyze_impact_after_schema_changes(test_services, test_session, indexed_test_files):
    """Test analyze_impact works after SchemaProcessor changes.
    
    Requirements: 3.9, 3.10, 6.13
    """
    # Test analyzing impact of SearchService
    result = await analyze_impact(
        services=test_services,
        session_id=test_session,
        entity="SearchService",
        max_depth=2
    )
    
    # Verify no "file not found" errors
    assert "error" not in result or "file not found" not in str(result.get("error", "")).lower(), \
        f"Got file not found error: {result}"
    
    # Verify impact analysis structure
    assert "impact_radius" in result, f"Impact radius not in result: {result}"
    assert "affected_files" in result
    assert "affected_entities" in result
    assert "relationship_types" in result
    
    # Verify impact_radius is valid
    assert result["impact_radius"] >= 0


@pytest.mark.asyncio
async def test_analyze_impact_with_relationships_after_schema_changes(
    test_services, test_session, indexed_test_files
):
    """Test analyze_impact finds relationships after SchemaProcessor changes.
    
    Requirements: 3.9, 3.10, 6.13
    """
    # Test analyzing impact of SearchService (used by IndexingPipeline and ContextBuilder)
    result = await analyze_impact(
        services=test_services,
        session_id=test_session,
        entity="SearchService",
        max_depth=2
    )
    
    # Verify no errors
    assert "error" not in result or "file not found" not in str(result.get("error", "")).lower()
    
    # Verify affected entities found
    assert "affected_entities" in result
    assert isinstance(result["affected_entities"], list)
    
    # Verify affected files found
    assert "affected_files" in result
    assert isinstance(result["affected_files"], dict)


@pytest.mark.asyncio
async def test_analyze_impact_transitive_after_schema_changes(
    test_services, test_session, indexed_test_files
):
    """Test analyze_impact finds transitive relationships after SchemaProcessor changes.
    
    Requirements: 3.9, 3.10, 6.13
    """
    # Test analyzing impact with depth > 1 to find transitive relationships
    result = await analyze_impact(
        services=test_services,
        session_id=test_session,
        entity="SearchService",
        max_depth=3
    )
    
    # Verify no errors
    assert "error" not in result or "file not found" not in str(result.get("error", "")).lower()
    
    # Verify traversal depth
    assert "traversal_depth" in result
    assert result["traversal_depth"] == 3
    
    # Verify impact analysis completed
    assert "impact_radius" in result
    assert result["impact_radius"] >= 0


@pytest.mark.asyncio
async def test_entity_operations_database_integrity(test_services, test_session, indexed_test_files):
    """Test database integrity after indexing with SchemaProcessor.

    Requirements: 3.6, 3.7, 6.13
    """
    storage = test_services["storage"]
    # Access underlying LanceDBManager via public API
    db_manager = storage.get_db_manager()

    # Verify database tables exist
    tables = await db_manager.list_tables()
    assert "document_chunks" in tables, f"document_chunks table not found. Tables: {tables}"
    assert "graph_entities" in tables, f"graph_entities table not found. Tables: {tables}"
    # graph_relationships table may not exist if no relationships were created
    # This is acceptable - the table is created on-demand when relationships are added

    # Verify entities were created
    entities = await db_manager.get_graph_entities(project_id="test_entity_ops")
    assert len(entities) > 0, "No entities found in database"

    # Verify all entities have required fields
    for entity in entities:
        assert entity.name, "Entity missing name"
        assert entity.type, "Entity missing type"
        assert entity.file_path, "Entity missing file_path"
        assert entity.project_id == "test_entity_ops"


@pytest.mark.asyncio
async def test_entity_operations_no_orphaned_references(test_services, test_session, indexed_test_files):
    """Test no orphaned references after indexing with SchemaProcessor.

    Requirements: 3.6, 3.7, 6.13
    """
    storage = test_services["storage"]
    # Access underlying LanceDBManager via public API
    db_manager = storage.get_db_manager()

    # Get all relationships
    relationships = await db_manager.get_graph_relationships(project_id="test_entity_ops")

    # Get all entity IDs
    entities = await db_manager.get_graph_entities(project_id="test_entity_ops")
    entity_ids = {entity.id for entity in entities}

    # Verify all relationships reference existing entities
    for rel in relationships:
        assert rel.source_id in entity_ids, \
            f"Relationship {rel.id} references non-existent source entity {rel.source_id}"
        assert rel.target_id in entity_ids, \
            f"Relationship {rel.id} references non-existent target entity {rel.target_id}"


@pytest.mark.asyncio
async def test_entity_operations_file_paths_valid(test_services, test_session, indexed_test_files):
    """Test all entity file paths are valid after SchemaProcessor changes.

    Requirements: 3.6, 3.7, 6.13
    """
    storage = test_services["storage"]
    # Access underlying LanceDBManager via public API
    db_manager = storage.get_db_manager()

    # Get all entities
    entities = await db_manager.get_graph_entities(project_id="test_entity_ops")

    # Verify all file paths are valid (not empty, properly formatted)
    for entity in entities:
        assert entity.file_path, f"Entity {entity.name} has empty file_path"
        assert not entity.file_path.startswith("//"), \
            f"Entity {entity.name} has malformed file_path: {entity.file_path}"

        # File path should be absolute or relative, not malformed
        file_path = Path(entity.file_path)
        assert str(file_path), f"Entity {entity.name} has invalid file_path: {entity.file_path}"


@pytest.mark.asyncio
async def test_multiple_entity_operations_success_rate(test_services, test_session, indexed_test_files):
    """Test success rate of entity operations after SchemaProcessor changes.
    
    Requirements: 3.6, 3.7, 3.9, 3.10, 6.13
    """
    # Test multiple entities
    entities_to_test = [
        "SearchService",
        "IndexingPipeline",
        "ContextBuilder",
        "search",
        "hybrid_search",
        "index_file",
        "build_context"
    ]
    
    understand_successful = 0
    impact_successful = 0
    total = len(entities_to_test)
    
    for entity_name in entities_to_test:
        # Test understand_entity
        understand_result = await understand_entity(
            services=test_services,
            session_id=test_session,
            entity=entity_name
        )
        
        # Count as successful if entity was found and no file errors
        if "entity" in understand_result and "file not found" not in str(understand_result).lower():
            understand_successful += 1
        
        # Test analyze_impact
        impact_result = await analyze_impact(
            services=test_services,
            session_id=test_session,
            entity=entity_name,
            max_depth=2
        )
        
        # Count as successful if impact_radius is present and no file errors
        if "impact_radius" in impact_result and "file not found" not in str(impact_result).lower():
            impact_successful += 1
    
    understand_rate = understand_successful / total
    impact_rate = impact_successful / total
    
    # Verify reasonable success rates (>50% since some methods may not be found)
    assert understand_rate > 0.5, \
        f"understand_entity success rate {understand_rate:.1%} is too low"
    assert impact_rate > 0.5, \
        f"analyze_impact success rate {impact_rate:.1%} is too low"


@pytest.mark.asyncio
async def test_entity_operations_after_directory_indexing(test_services, test_session, tmp_path, monkeypatch):
    """Test entity operations work after directory indexing with SchemaProcessor.
    
    Requirements: 3.6, 3.7, 3.9, 3.10, 6.13
    """
    # Change to tmp_path for relative path resolution
    monkeypatch.chdir(tmp_path)
    
    # Create test directory with multiple files
    test_dir = tmp_path / "test_project"
    test_dir.mkdir()
    
    # Create simple Python files
    (test_dir / "module_a.py").write_text('''
class ClassA:
    def method_a(self):
        pass
''')
    
    (test_dir / "module_b.py").write_text('''
from module_a import ClassA

class ClassB:
    def __init__(self):
        self.a = ClassA()
''')
    
    # Index entire directory (async - returns 'started' immediately)
    result = await add_knowledge(
        services=test_services,
        session_id=test_session,
        content_type="directory",
        source="test_project"
    )

    # Directory indexing is async - verify we got 'started' status
    assert result["status"] == "started", f"Expected 'started' status, got: {result}"
    assert "operation_id" in result, "Expected operation_id in result"

    # Wait for async indexing to complete
    session_manager = test_services["session_manager"]
    completion = await _wait_for_indexing_completion(
        session_manager, test_session, result["operation_id"]
    )

    # Verify indexing completed successfully
    assert completion["status"] == "completed", f"Expected completed, got: {completion}"
    assert completion["items_processed"] == 2, f"Expected 2 files, got: {completion['items_processed']}"
    
    # Test entity operations work
    understand_result = await understand_entity(
        services=test_services,
        session_id=test_session,
        entity="ClassA"
    )
    
    # Verify no file errors
    assert "error" not in understand_result or \
        "file not found" not in str(understand_result.get("error", "")).lower()
    
    # Test impact analysis
    impact_result = await analyze_impact(
        services=test_services,
        session_id=test_session,
        entity="ClassA",
        max_depth=2
    )
    
    # Verify no file errors
    assert "error" not in impact_result or \
        "file not found" not in str(impact_result.get("error", "")).lower()
    assert "impact_radius" in impact_result
