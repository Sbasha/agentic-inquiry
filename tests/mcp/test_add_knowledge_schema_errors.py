"""Tests for add_knowledge tool schema validation error handling."""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock, patch

from agent_vault.mcp.tools.knowledge import add_knowledge
from agent_vault.exceptions import SchemaValidationError

# Patch path for IndexingPipeline class (patched at the actual module where it's defined)
PIPELINE_PATCH_PATH = "agent_vault.indexing.pipeline.IndexingPipeline"
PARSER_CHAIN_PATCH_PATH = "agent_vault.mcp.tools.knowledge.create_parser_chain"


@pytest.fixture
def mcp_services():
    """Create mock services."""
    session_manager = AsyncMock()
    session_manager.validate_session.return_value = True
    
    session = MagicMock()
    session.project_id = "test_project"
    session_manager.get_session.return_value = session
    
    # Mock get_events to return empty list initially (will be updated by add_event calls)
    session_manager._events = []
    
    async def mock_add_event(session_id, event_type, data):
        """Mock add_event that stores events."""
        session_manager._events.append({
            "event_type": event_type,
            "data": data
        })
    
    async def mock_get_events(session_id):
        """Mock get_events that returns stored events."""
        return session_manager._events
    
    session_manager.add_event = mock_add_event
    session_manager.get_events = mock_get_events
    
    event_system = AsyncMock()
    event_system.emit = AsyncMock()
    
    config = MagicMock()
    config.storage.root = "/test/root"
    config.progress.enabled = False
    
    mock_db_manager = AsyncMock()
    
    return {
        "session_manager": session_manager,
        "event_system": event_system,
        "config": config,
        "storage": mock_db_manager,  # Use correct key name
    }


@pytest.mark.asyncio
async def test_add_knowledge_file_schema_validation_error(mcp_services, tmp_path, monkeypatch):
    """Test that schema validation errors are handled gracefully for file indexing."""
    # Create a test file
    test_file = tmp_path / "test.py"
    test_file.write_text("def test():\n    pass")
    
    # Mock os.getcwd() to return tmp_path so path validation passes
    monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))
    
    # Mock the indexing pipeline to raise SchemaValidationError
    with patch(PIPELINE_PATCH_PATH) as mock_create_pipeline:
        mock_pipeline = MagicMock()
        mock_pipeline.process_document = AsyncMock(
            side_effect=SchemaValidationError(
                table_name="document_chunks",
                missing_fields=["id", "content"],
                type_mismatches=[("field1", "string", "int")]
            )
        )
        mock_create_pipeline.return_value = mock_pipeline
        
        # Mock parser chain
        with patch(PARSER_CHAIN_PATCH_PATH) as mock_create_chain:
            from agent_vault.parsers.models import ParsedDocument, ParserChunk
            
            mock_chain = MagicMock()
            mock_chain.parse = AsyncMock(return_value=ParsedDocument(
                doc_id="test_doc",
                file_path=str(test_file),
                chunks=[ParserChunk(
                    content="test",
                    line_start=1,
                    line_end=1,
                    symbols=[],
                    relationships=[],
                    metadata={}
                )]
            ))
            mock_create_chain.return_value = mock_chain
            
            # Call add_knowledge
            result = await add_knowledge(
                services=mcp_services,
                session_id="test_session",
                content_type="file",
                source=str(test_file)
            )
            
            # Verify error response
            assert result["status"] == "failed"
            assert result["error_type"] == "schema_validation"
            assert "details" in result
            assert "missing_fields" in result["details"]
            assert "id" in result["details"]["missing_fields"]
            assert "content" in result["details"]["missing_fields"]
            assert "correlation_id" in result["details"]


@pytest.mark.asyncio
async def test_add_knowledge_directory_schema_validation_error(mcp_services, tmp_path, monkeypatch):
    """Test that schema validation errors are handled gracefully for directory indexing."""
    # Create test files
    test_dir = tmp_path / "test_dir"
    test_dir.mkdir()
    (test_dir / "file1.py").write_text("def test1(): pass")
    (test_dir / "file2.py").write_text("def test2(): pass")
    
    # Mock os.getcwd() to return tmp_path so path validation passes
    monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))
    
    # Mock the indexing pipeline to raise SchemaValidationError for first file
    with patch(PIPELINE_PATCH_PATH) as mock_create_pipeline:
        mock_pipeline = MagicMock()

        # First call raises error, second succeeds
        call_count = 0
        async def process_side_effect(doc, flush_relationships=True):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SchemaValidationError(
                    table_name="document_chunks",
                    missing_fields=["required_field"]
                )

        mock_pipeline.process_document = AsyncMock(side_effect=process_side_effect)
        # Add async mocks for relationship methods (called after indexing)
        mock_pipeline.flush_pending_relationships = AsyncMock(return_value=0)
        mock_pipeline.get_resolution_stats = MagicMock(return_value={})
        mock_create_pipeline.return_value = mock_pipeline
        
        # Mock parser chain
        with patch(PARSER_CHAIN_PATCH_PATH) as mock_create_chain:
            from agent_vault.parsers.models import ParsedDocument, ParserChunk
            
            mock_chain = MagicMock()
            mock_chain.parse = AsyncMock(return_value=ParsedDocument(
                doc_id="test_doc",
                file_path="test.py",
                chunks=[ParserChunk(
                    content="test",
                    line_start=1,
                    line_end=1,
                    symbols=[],
                    relationships=[],
                    metadata={}
                )]
            ))
            mock_create_chain.return_value = mock_chain
            
            # Mock ignore handler
            with patch("agent_vault.mcp.tools.knowledge.get_ignore_handler") as mock_ignore:
                mock_handler = MagicMock()
                mock_handler.is_ignored.return_value = False
                mock_ignore.return_value = mock_handler
                
                # Call add_knowledge (now async)
                result = await add_knowledge(
                    services=mcp_services,
                    session_id="test_session",
                    content_type="directory",
                    source=str(test_dir)
                )
                
                # Verify async indexing started
                assert result["status"] == "started"
                assert "operation_id" in result
                
                # Poll for completion (with timeout)
                import asyncio
                session_manager = mcp_services["session_manager"]
                timeout = 30  # seconds
                loop = asyncio.get_running_loop()
                start_time = loop.time()
                completed = False
                final_event = None
                
                while loop.time() - start_time < timeout:
                    # Get events from session
                    events = await session_manager.get_events("test_session")
                    
                    # Check for completion
                    for event in events:
                        if event.get("event_type") == "indexing_completed":
                            if event.get("data", {}).get("operation_id") == result["operation_id"]:
                                completed = True
                                final_event = event
                                break
                    
                    if completed:
                        break
                    
                    # Wait before polling again
                    await asyncio.sleep(0.5)
                
                # Verify completion
                if not completed:
                    pytest.fail(f"Indexing did not complete within {timeout} seconds")
                
                # Verify partial success - only one file succeeded (the other had schema error)
                assert final_event is not None
                assert final_event["data"]["items_processed"] == 1  # One succeeded
                # Errors are logged but not included in completion event


@pytest.mark.asyncio
async def test_add_knowledge_text_schema_validation_error(mcp_services):
    """Test that schema validation errors are handled gracefully for text indexing."""
    # Mock the indexing pipeline to raise SchemaValidationError
    with patch(PIPELINE_PATCH_PATH) as mock_create_pipeline:
        mock_pipeline = MagicMock()
        mock_pipeline.process_document = AsyncMock(
            side_effect=SchemaValidationError(
                table_name="document_chunks",
                missing_fields=["vector"],
                type_mismatches=[]
            )
        )
        mock_create_pipeline.return_value = mock_pipeline
        
        # Call add_knowledge with text
        result = await add_knowledge(
            services=mcp_services,
            session_id="test_session",
            content_type="text",
            source="This is test text content"
        )
        
        # Verify error response
        assert result["status"] == "failed"
        assert result["error_type"] == "schema_validation"
        assert "details" in result
        assert "missing_fields" in result["details"]
        assert "vector" in result["details"]["missing_fields"]
        assert "correlation_id" in result["details"]


@pytest.mark.asyncio
async def test_add_knowledge_schema_error_includes_hints(mcp_services, tmp_path, monkeypatch):
    """Test that schema validation errors include helpful hints."""
    # Create a test file
    test_file = tmp_path / "test.py"
    test_file.write_text("def test(): pass")
    
    # Mock os.getcwd() to return tmp_path so path validation passes
    monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))
    
    # Mock the indexing pipeline to raise SchemaValidationError with type mismatches
    with patch(PIPELINE_PATCH_PATH) as mock_create_pipeline:
        mock_pipeline = MagicMock()
        mock_pipeline.process_document = AsyncMock(
            side_effect=SchemaValidationError(
                table_name="document_chunks",
                missing_fields=[],
                type_mismatches=[("line_start", "int", "str")]
            )
        )
        mock_create_pipeline.return_value = mock_pipeline
        
        # Mock parser chain
        with patch(PARSER_CHAIN_PATCH_PATH) as mock_create_chain:
            from agent_vault.parsers.models import ParsedDocument, ParserChunk
            
            mock_chain = MagicMock()
            mock_chain.parse = AsyncMock(return_value=ParsedDocument(
                doc_id="test_doc",
                file_path=str(test_file),
                chunks=[ParserChunk(
                    content="test",
                    line_start=1,
                    line_end=1,
                    symbols=[],
                    relationships=[],
                    metadata={}
                )]
            ))
            mock_create_chain.return_value = mock_chain
            
            # Call add_knowledge
            result = await add_knowledge(
                services=mcp_services,
                session_id="test_session",
                content_type="file",
                source=str(test_file)
            )
            
            # Verify hint is included
            assert "hint" in result["details"]
            assert "type" in result["details"]["hint"].lower()
            assert "type_mismatches" in result["details"]
