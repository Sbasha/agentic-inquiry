"""Tests for critical bug fixes from task 3.

This module tests the three critical bug fixes:
1. Config thread safety (already tested in test_config_storage.py)
2. RelationshipResolver database query implementation
3. LanceDBManager async table creation (already tested in test_lancedb_manager.py)
"""
import pytest

from agent_vault.indexing.relationship_resolver import RelationshipResolver
from agent_vault.indexing.symbol_registry import SymbolRegistry
from tests.utils.in_memory_lancedb_manager import InMemoryLanceDBManager


@pytest.mark.asyncio
async def test_relationship_resolver_database_query():
    """Test that RelationshipResolver can query existing relationships from database.
    
    This tests the fix for the incomplete _resolve_from_database implementation.
    The actual format of IDs is complex (type::hash::file::name), so we test
    with realistic data that matches the expected format.
    """
    # Set up database with existing relationships
    mock_db_manager = InMemoryLanceDBManager(uri="memory://test-db-query")
    await mock_db_manager.create_tables_and_indexes()
    await mock_db_manager.connect()
    
    # Add relationships with realistic ID format
    # Format: "type::project_hash::file_path::symbol_name"
    await mock_db_manager.add_graph_relationships([
        {
            "id": "rel-1",
            "source_id": "class::abc123::src/module_a.py::ClassA",
            "target_id": "class::abc123::src/module_b.py::ClassB",
            "type": "imports",
            "project_id": "test_proj",
            "vector": [1.0, 0.0],
        },
        {
            "id": "rel-2",
            "source_id": "function::abc123::src/module_c.py::FunctionC",
            "target_id": "function::abc123::src/utils.py::helper_function",
            "type": "imports",
            "project_id": "test_proj",
            "vector": [0.0, 1.0],
        },
    ])
    
    # Create resolver with database
    symbol_registry = SymbolRegistry(project_root=".", project_id="test_proj")
    resolver = RelationshipResolver(
        symbol_registry=symbol_registry,
        db_manager=mock_db_manager,
        project_root="."
    )
    
    # Test resolving from database
    result = await resolver._resolve_from_database(
        target_name="ClassB",
        source_file="src/module_a.py"
    )
    
    # Should find the relationship
    assert result is not None
    target_file, target_type, confidence = result
    assert target_file == "src/module_b.py"
    assert target_type == "class"
    assert confidence == 1.0
    
    # Test with different relationship
    result = await resolver._resolve_from_database(
        target_name="helper_function",
        source_file="src/module_c.py"
    )
    
    assert result is not None
    target_file, target_type, confidence = result
    assert target_file == "src/utils.py"
    assert target_type == "function"
    assert confidence == 1.0


@pytest.mark.asyncio
async def test_relationship_resolver_database_query_no_match():
    """Test that _resolve_from_database returns None when no match is found."""
    mock_db_manager = InMemoryLanceDBManager(uri="memory://test-db-no-match")
    await mock_db_manager.create_tables_and_indexes()
    await mock_db_manager.connect()
    
    # Add a relationship with realistic ID format
    await mock_db_manager.add_graph_relationships([
        {
            "id": "rel-1",
            "source_id": "class::abc123::src/module_a.py::ClassA",
            "target_id": "class::abc123::src/module_b.py::ClassB",
            "type": "imports",
            "project_id": "test_proj",
            "vector": [1.0, 0.0],
        },
    ])
    
    symbol_registry = SymbolRegistry(project_root=".", project_id="test_proj")
    resolver = RelationshipResolver(
        symbol_registry=symbol_registry,
        db_manager=mock_db_manager,
        project_root="."
    )
    
    # Try to resolve a non-existent relationship
    result = await resolver._resolve_from_database(
        target_name="NonExistentClass",
        source_file="src/module_a.py"
    )
    
    # Should return None
    assert result is None


@pytest.mark.asyncio
async def test_relationship_resolver_database_query_no_db():
    """Test that _resolve_from_database handles missing database gracefully."""
    symbol_registry = SymbolRegistry(project_root=".", project_id="test_proj")
    resolver = RelationshipResolver(
        symbol_registry=symbol_registry,
        db_manager=None,  # No database
        project_root="."
    )
    
    # Should return None gracefully
    result = await resolver._resolve_from_database(
        target_name="ClassB",
        source_file="src/module_a.py"
    )
    
    assert result is None


@pytest.mark.asyncio
async def test_lancedb_manager_async_table_creation():
    """Test that create_tables_and_indexes is truly async.
    
    This verifies the fix for the async/sync mixing bug.
    """
    mock_db_manager = InMemoryLanceDBManager(uri="memory://test-async-creation")
    
    # Should be able to await the method
    await mock_db_manager.create_tables_and_indexes()
    
    # Verify tables were created
    assert "document_chunks" in mock_db_manager._tables
    assert "graph_entities" in mock_db_manager._tables
    assert "graph_relationships" in mock_db_manager._tables
    
    # Verify database is initialized
    assert mock_db_manager.db is not None


@pytest.mark.asyncio
async def test_lancedb_manager_async_table_creation_with_data():
    """Test that async table creation works with subsequent data operations."""
    mock_db_manager = InMemoryLanceDBManager(uri="memory://test-async-with-data")
    
    # Create tables asynchronously
    await mock_db_manager.create_tables_and_indexes()
    await mock_db_manager.connect()
    
    # Add data
    await mock_db_manager.add_document_chunks([
        {
            "id": "chunk-1",
            "doc_id": "doc-1",
            "project_id": "test_proj",
            "vector": [1.0, 0.0],
            "content": "Test content",
            "file_path": "/test/file.py",
            "content_type": "code",
        }
    ])    
    # Verify data was added
    results = await mock_db_manager.vector_search(
        "document_chunks",
        [1.0, 0.0],
        "vector",
        10,
        filters=None
    )
    
    assert len(results) == 1
    assert results[0]["id"] == "chunk-1"



def test_env_var_validation_valid_variables(monkeypatch, tmp_path):
    """Test that valid environment variables are accepted and applied."""
    from agent_vault.config import Config
    
    # Create a temporary config file with all required sections
    config_file = tmp_path / "mock_config.yaml"
    config_file.write_text("""
storage:
  root: ./.agv
  default_project_id: test_project
  lancedb:
    path: lancedb
  file_tracker:
    path: file_tracker.db
  document_cache:
    enabled: false
    path: document_cache
cache:
  document_cache:
    max_size: 1000
search:
  default_limit: 10
  max_limit: 100
embeddings:
  default_provider: sentence_transformer
parsers:
  unified_code:
    enabled: true
  document:
    enabled: true
  fallback_text:
    enabled: true
""")
    
    # Set valid environment variables
    monkeypatch.setenv("AGV_STORAGE_ROOT", "./custom_data")
    monkeypatch.setenv("AGV_STORAGE_DEFAULT_PROJECT_ID", "custom_project")
    monkeypatch.setenv("AGV_CACHE_DOCUMENT_CACHE_MAX_SIZE", "5000")
    monkeypatch.setenv("AGV_SEARCH_DEFAULT_LIMIT", "25")
    
    # Load config
    config = Config.load(str(config_file))
    
    # Verify overrides were applied
    assert config.storage.root == "./custom_data"
    assert config.storage.default_project_id == "custom_project"
    assert config.cache.document_cache.max_size == 5000
    assert config.search.default_limit == 25


def test_env_var_validation_typo_detection(monkeypatch, tmp_path, caplog):
    """Test that typos in section names are detected and logged.

    Note: Currently, only section-level typos are detected. Option-level typos
    (e.g., DEFAUT_PROJECT_ID instead of DEFAULT_PROJECT_ID) are silently ignored.
    This could be enhanced in the future with fuzzy matching.
    """
    import logging
    from agent_vault.config import Config

    # Create a temporary config file with all required sections
    config_file = tmp_path / "mock_config.yaml"
    config_file.write_text("""
storage:
  root: ./.agv
  lancedb:
    path: lancedb
  file_tracker:
    path: file_tracker.db
  document_cache:
    enabled: false
    path: document_cache
cache:
  document_cache:
    max_size: 1000
search:
  default_limit: 10
  max_limit: 100
embeddings:
  default_provider: sentence_transformer
parsers:
  unified_code:
    enabled: true
  document:
    enabled: true
  fallback_text:
    enabled: true
""")

    # Set environment variables with typos
    # NOTE: Option-level typos (DEFAUT_PROJECT_ID) are silently ignored
    # Only section-level typos (STORAG, DOCUMNT) are detected
    monkeypatch.setenv("AGV_STORAG_ROOT", "./typo_data")  # typo: STORAG instead of STORAGE
    monkeypatch.setenv("AGV_DATABSE_PATH", "./db")  # typo: DATABSE instead of DATABASE (not valid anyway)

    # Load config with logging
    with caplog.at_level(logging.WARNING):
        Config.load(str(config_file))

    # Verify warnings were logged for section-level typos
    warning_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]

    # Should have warnings about invalid section names
    assert any("AGV_STORAG_ROOT" in msg for msg in warning_messages)

    # Warning should list valid sections
    assert any("storage" in msg and "cache" in msg for msg in warning_messages)


def test_env_var_validation_invalid_section(monkeypatch, tmp_path, caplog):
    """Test that invalid top-level sections are detected."""
    import logging
    from agent_vault.config import Config
    
    # Create a temporary config file with all required sections
    config_file = tmp_path / "mock_config.yaml"
    config_file.write_text("""
storage:
  root: ./.agv
  lancedb:
    path: lancedb
  file_tracker:
    path: file_tracker.db
  document_cache:
    enabled: false
    path: document_cache
cache:
  document_cache:
    max_size: 1000
search:
  default_limit: 10
  max_limit: 100
embeddings:
  default_provider: sentence_transformer
parsers:
  unified_code:
    enabled: true
  document:
    enabled: true
  fallback_text:
    enabled: true
""")
    
    # Set environment variables with invalid sections
    monkeypatch.setenv("AGV_INVALID_SECTION_KEY", "value")
    monkeypatch.setenv("AGV_DATABASE_PATH", "./db")  # DATABASE is not a valid section
    
    # Load config with logging
    with caplog.at_level(logging.WARNING):
        Config.load(str(config_file))
    
    # Verify warnings were logged
    warning_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]
    
    # Should warn about invalid sections
    assert any("invalid_section" in msg.lower() for msg in warning_messages)
    assert any("database" in msg.lower() for msg in warning_messages)
    
    # Should list valid sections
    assert any("storage" in msg and "cache" in msg and "search" in msg for msg in warning_messages)


def test_env_var_validation_warning_messages(monkeypatch, tmp_path, caplog):
    """Test that warning messages provide helpful suggestions for section-level typos.

    Note: Currently, only section-level typos generate warnings with suggestions.
    Option-level typos are silently ignored.
    """
    import logging
    from agent_vault.config import Config

    # Create a temporary config file with all required sections
    config_file = tmp_path / "mock_config.yaml"
    config_file.write_text("""
storage:
  root: ./.agv
  lancedb:
    path: lancedb
  file_tracker:
    path: file_tracker.db
  document_cache:
    enabled: false
    path: document_cache
cache:
  document_cache:
    max_size: 1000
search:
  default_limit: 10
  max_limit: 100
embeddings:
  default_provider: sentence_transformer
parsers:
  unified_code:
    enabled: true
  document:
    enabled: true
  fallback_text:
    enabled: true
""")

    # Set an environment variable with a section-level typo
    monkeypatch.setenv("AGV_STORAG_ROOT", "./test")  # typo: STORAG instead of STORAGE

    # Load config with logging
    with caplog.at_level(logging.WARNING):
        Config.load(str(config_file))

    # Verify warning message format
    warning_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]

    # Should have a clear warning about the section typo
    typo_warnings = [msg for msg in warning_messages if "AGV_STORAG_ROOT" in msg]
    assert len(typo_warnings) > 0, f"Expected warning about AGV_STORAG_ROOT, got: {warning_messages}"

    # Warning should list valid sections as suggestions
    assert any("storage" in msg for msg in typo_warnings), "Warning should list 'storage' as valid section"
