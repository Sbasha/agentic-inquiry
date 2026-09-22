"""Unit tests for the production LanceDB manager helpers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List

import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.config import Config, StorageConfig, LanceDBConfig
from agentic_inquiry.database.lancedb_manager import LanceDBManager, SyncLanceDBManager
from tests.utils.in_memory_lancedb_manager import InMemoryLanceDBManager


@dataclass
class _Index:
    columns: List[str]


class _DummyTable:
    def __init__(self) -> None:
        self.indices: List[List[str]] = []

    def list_indices(self):
        return [_Index(columns=list(columns)) for columns in self.indices]

    def create_index(self, *, vector_column_name: str, **_: object) -> None:
        self.indices.append([vector_column_name])

    def create_fts_index(self, column: str, **_: object) -> None:
        self.indices.append([column])


class _DummyConnection:
    def __init__(self, table: _DummyTable) -> None:
        self.table = table
        self.open_calls: List[str] = []

    def open_table(self, name: str):
        self.open_calls.append(name)
        return self.table


def test_injected_connection_factory_skips_local_path(monkeypatch):
    table = _DummyTable()
    connection = _DummyConnection(table)

    def fail_makedirs(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("os.makedirs should not be called for remote URIs")

    monkeypatch.setattr("os.makedirs", fail_makedirs)

    calls = []

    def factory():
        calls.append(True)
        return connection

    manager = LanceDBManager(
        uri="s3://remote-database/path",
        connection_factory=factory,
        table_configs={},
    )

    connected = asyncio.run(manager.connect())
    assert connected is manager
    # Access connection via ConnectionManager (internal detail but necessary for test)
    assert manager._conn_manager._ensure_db_sync() is connection
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_custom_table_configs_apply_indexes():
    table = _DummyTable()
    connection = _DummyConnection(table)

    manager = LanceDBManager(
        connection=connection,
        table_configs={
            "custom": {
                "vector_columns": ("vector_a",),
                "fts_columns": ("body",),
            }
        },
    )

    await manager.create_tables_and_indexes()

    assert connection.open_calls == ["custom"]
    assert ["vector_a"] in table.indices
    assert ["body"] in table.indices


def test_sync_manager_wraps_async_methods():
    async_manager = InMemoryLanceDBManager(uri=":memory:", project_id="test_proj")

    with SyncLanceDBManager(manager=async_manager) as manager:
        manager.create_tables_and_indexes()
        manager.add_document_chunks(
            [
                {
                    "id": "doc-1",
                    "doc_id": "doc-1",
                    "project_id": "test_proj",
                    "file_path": "test.py",
                    "content_type": "code",
                    "vector": [1.0, 0.0],
                    "content": "Example",
                }
            ]
        )

        results = manager.vector_search(
            "document_chunks", [1.0, 0.0], "vector", 1, filters=None
        )

        assert len(results) == 1
        assert results[0]["id"] == "doc-1"
        assert results[0]["project_id"] == "test_proj"


def test_manager_with_config(tmp_path):
    """Test LanceDBManager initialization with Config object."""
    storage_root = tmp_path / "test_storage"

    # Create config with custom storage
    config = Config(
        storage=StorageConfig(
            root=str(storage_root),
            default_project_id="test_project",  # Use default_project_id instead
            lancedb=LanceDBConfig(path="lancedb"),
        )
    )

    # Initialize manager with config
    manager = LanceDBManager(config=config)

    # Verify project_id is set from config default
    assert manager._project_id == "test_project"

    # Verify URI is resolved from config
    expected_uri = str(storage_root / "lancedb")
    assert manager.uri == expected_uri

    # Directories are NOT created at construction time (lazy initialization)
    # They are created when connect() or initialize() is called
    assert not storage_root.exists(), "Directories should not exist at construction time"

    # Directories are created when connected
    asyncio.run(manager.connect())
    assert storage_root.exists()
    assert (storage_root / "lancedb").exists()


def test_manager_project_id_filtering():
    """Test that queries automatically filter by project_id."""
    manager = InMemoryLanceDBManager(uri=":memory:", project_id="proj_a")
    
    # Create tables
    asyncio.run(manager.create_tables_and_indexes())
    
    # Add chunks for different projects
    asyncio.run(manager.add_document_chunks([
        {
            "id": "chunk-1",
            "doc_id": "doc-1",
            "project_id": "proj_a",
            "file_path": "test.py",
            "content_type": "code",
            "vector": [1.0, 0.0],
            "content": "Project A content",
        },
        {
            "id": "chunk-2",
            "doc_id": "doc-2",
            "project_id": "proj_b",
            "file_path": "test.py",
            "content_type": "code",
            "vector": [0.0, 1.0],
            "content": "Project B content",
        },
        {
            "id": "chunk-3",
            "doc_id": "doc-3",
            "project_id": "proj_a",
            "file_path": "test.py",
            "content_type": "code",
            "vector": [1.0, 1.0],
            "content": "Another Project A content",
        },
    ]))
    
    # Search with default project_id (should use "current" = proj_a)
    results = asyncio.run(manager.vector_search(
        "document_chunks", [1.0, 0.0], "vector", 10, filters=None
    ))
    
    # Should only return proj_a chunks
    assert len(results) == 2
    assert all(r["project_id"] == "proj_a" for r in results)
    assert {r["id"] for r in results} == {"chunk-1", "chunk-3"}


def test_manager_explicit_project_id_filtering():
    """Test explicit project_id filtering in queries."""
    manager = InMemoryLanceDBManager(uri=":memory:", project_id="proj_a")
    
    # Create tables
    asyncio.run(manager.create_tables_and_indexes())
    
    # Add chunks for different projects
    asyncio.run(manager.add_document_chunks([
        {
            "id": "chunk-1",
            "doc_id": "doc-1",
            "project_id": "proj_a",
            "file_path": "test_a.py",
            "content_type": "code",
            "vector": [1.0, 0.0],
            "content": "Project A content",
        },
        {
            "id": "chunk-2",
            "doc_id": "doc-2",
            "project_id": "proj_b",
            "file_path": "test_b.py",
            "content_type": "code",
            "vector": [0.0, 1.0],
            "content": "Project B content",
        },
    ]))

    # Search with explicit project_id
    results = asyncio.run(manager.vector_search(
        "document_chunks", [1.0, 0.0], "vector", 10, filters=None, project_id="proj_b"
    ))
    
    # Should only return proj_b chunks
    assert len(results) == 1
    assert results[0]["project_id"] == "proj_b"
    assert results[0]["id"] == "chunk-2"


def test_manager_search_all_projects():
    """Test searching across all projects with project_id=None."""
    manager = InMemoryLanceDBManager(uri=":memory:", project_id="proj_a")
    
    # Create tables
    asyncio.run(manager.create_tables_and_indexes())
    
    # Add chunks for different projects
    asyncio.run(manager.add_document_chunks([
        {
            "id": "chunk-1",
            "doc_id": "doc-1",
            "project_id": "proj_a",
            "file_path": "test_a.py",
            "content_type": "code",
            "vector": [1.0, 0.0],
            "content": "Project A content",
        },
        {
            "id": "chunk-2",
            "doc_id": "doc-2",
            "project_id": "proj_b",
            "file_path": "test_b.py",
            "content_type": "code",
            "vector": [0.0, 1.0],
            "content": "Project B content",
        },
        {
            "id": "chunk-3",
            "doc_id": "doc-3",
            "project_id": "proj_c",
            "file_path": "test_c.py",
            "content_type": "code",
            "vector": [1.0, 1.0],
            "content": "Project C content",
        },
    ]))

    # Search with project_id=None (all projects)
    results = asyncio.run(manager.vector_search(
        "document_chunks", [1.0, 0.0], "vector", 10, filters=None, project_id=None
    ))
    
    # Should return all chunks
    assert len(results) == 3
    assert {r["id"] for r in results} == {"chunk-1", "chunk-2", "chunk-3"}


def test_manager_cross_project_query():
    """Test query_across_projects method."""
    manager = InMemoryLanceDBManager(uri=":memory:", project_id="proj_a")
    
    # Create tables
    asyncio.run(manager.create_tables_and_indexes())
    
    # Add entities for different projects
    asyncio.run(manager.add_graph_entities([
        {
            "id": "entity-1",
            "name": "ClassA",
            "type": "class",
            "project_id": "proj_a",
            "file_path": "test_a.py",
            "vector": [1.0, 0.0],
        },
        {
            "id": "entity-2",
            "name": "ClassB",
            "type": "class",
            "project_id": "proj_b",
            "file_path": "test_b.py",
            "vector": [0.0, 1.0],
        },
        {
            "id": "entity-3",
            "name": "ClassC",
            "type": "class",
            "project_id": "proj_c",
            "file_path": "test_c.py",
            "vector": [1.0, 1.0],
        },
    ]))
    
    # Query across specific projects
    results = asyncio.run(manager.query_across_projects(
        "graph_entities",
        project_ids=["proj_a", "proj_c"],
        limit=10
    ))
    
    # Should only return entities from proj_a and proj_c
    assert len(results) == 2
    assert {r["id"] for r in results} == {"entity-1", "entity-3"}
    assert {r["project_id"] for r in results} == {"proj_a", "proj_c"}


def test_manager_fts_search_with_project_filtering():
    """Test full-text search respects project_id filtering."""
    manager = InMemoryLanceDBManager(uri=":memory:", project_id="proj_a")
    
    # Create tables
    asyncio.run(manager.create_tables_and_indexes())
    
    # Add chunks for different projects
    asyncio.run(manager.add_document_chunks([
        {
            "id": "chunk-1",
            "doc_id": "doc-1",
            "project_id": "proj_a",
            "file_path": "test_a.py",
            "content_type": "code",
            "vector": [1.0, 0.0],
            "content": "Python programming tutorial",
            "fts_text": "Python programming tutorial",
        },
        {
            "id": "chunk-2",
            "doc_id": "doc-2",
            "project_id": "proj_b",
            "file_path": "test_b.py",
            "content_type": "code",
            "vector": [0.0, 1.0],
            "content": "Python data science guide",
            "fts_text": "Python data science guide",
        },
    ]))
    
    # FTS search with default project_id
    results = asyncio.run(manager.fts_search(
        "document_chunks", "Python", 10, filters=None
    ))
    
    # Should only return proj_a chunks
    assert len(results) == 1
    assert results[0]["project_id"] == "proj_a"
    assert results[0]["id"] == "chunk-1"


def test_manager_advanced_filter_with_project_filtering():
    """Test advanced_filter respects project_id filtering."""
    manager = InMemoryLanceDBManager(uri=":memory:", project_id="proj_a")
    
    # Create tables
    asyncio.run(manager.create_tables_and_indexes())
    
    # Add relationships for different projects
    asyncio.run(manager.add_graph_relationships([
        {
            "id": "rel-1",
            "source_id": "entity-1",
            "target_id": "entity-2",
            "type": "calls",
            "project_id": "proj_a",
            "vector": [1.0, 0.0],
        },
        {
            "id": "rel-2",
            "source_id": "entity-3",
            "target_id": "entity-4",
            "type": "imports",
            "project_id": "proj_b",
            "vector": [0.0, 1.0],
        },
        {
            "id": "rel-3",
            "source_id": "entity-5",
            "target_id": "entity-6",
            "type": "calls",
            "project_id": "proj_a",
            "vector": [1.0, 1.0],
        },
    ]))
    
    # Filter by type with default project_id
    results = asyncio.run(manager.advanced_filter(
        "graph_relationships",
        filters={"type": "calls"},
        limit=10
    ))
    
    # Should only return proj_a relationships of type "calls"
    assert len(results) == 2
    assert all(r["project_id"] == "proj_a" for r in results)
    assert all(r["type"] == "calls" for r in results)
    assert {r["id"] for r in results} == {"rel-1", "rel-3"}


def test_manager_custom_storage_path(tmp_path):
    """Test LanceDBManager with custom storage path from config."""
    custom_storage = tmp_path / "custom_db_location"

    # Create config with custom path
    config = Config(
        storage=StorageConfig(
            root=str(tmp_path / "storage_root"),
            default_project_id="custom_proj",  # Use default_project_id
            lancedb=LanceDBConfig(path=str(custom_storage)),
        )
    )

    # Initialize manager
    manager = LanceDBManager(config=config)

    # Verify custom path is used
    assert manager.uri == str(custom_storage)
    assert manager._project_id == "custom_proj"

    # Directories are NOT created at construction time (lazy initialization)
    assert not custom_storage.exists(), "Directory should not exist at construction time"

    # Directories are created when connected
    asyncio.run(manager.connect())
    assert custom_storage.exists()



@pytest.mark.asyncio
async def test_connection_lifecycle(tmp_path):
    """Test connection lifecycle management (connect, close, reconnect)."""
    storage_root = tmp_path / "test_storage"
    uri = str(storage_root / "lancedb")
    
    manager = LanceDBManager(uri=uri)
    
    # Initially not connected
    assert not manager.is_connected()
    
    # Connect
    await manager.connect()
    assert manager.is_connected()
    
    # Close
    await manager.close()
    assert not manager.is_connected()
    
    # Reconnect
    await manager.reconnect()
    assert manager.is_connected()
    
    # Clean up
    await manager.close()


@pytest.mark.asyncio
async def test_async_context_manager(tmp_path):
    """Test using LanceDBManager as async context manager."""
    storage_root = tmp_path / "test_storage"
    uri = str(storage_root / "lancedb")
    
    # Use as context manager
    async with LanceDBManager(uri=uri) as manager:
        assert manager.is_connected()
        # Manager should be usable within context
        await manager.connect()  # Should be idempotent
    
    # After exiting context, connection should be closed
    assert not manager.is_connected()


@pytest.mark.asyncio
async def test_health_check(tmp_path):
    """Test database health check."""
    storage_root = tmp_path / "test_storage"
    uri = str(storage_root / "lancedb")
    
    manager = LanceDBManager(uri=uri)
    
    # Health check should fail when not connected
    assert not await manager.health_check()
    
    # Connect and health check should pass
    await manager.connect()
    assert await manager.health_check()
    
    # Close and health check should fail again
    await manager.close()
    assert not await manager.health_check()


@pytest.mark.asyncio
async def test_query_entities_method(mock_db_manager):
    """Test query_entities convenience method."""
    
    # Add some test entities
    test_entities = [
        {
            "id": "entity_1",
            "name": "TestClass",
            "type": "class",
            "file_path": "test.py",
            "project_id": "test_project",
        },
        {
            "id": "entity_2",
            "name": "test_function",
            "type": "function",
            "file_path": "test.py",
            "project_id": "test_project",
        },
    ]
    
    await mock_db_manager.add_graph_entities(test_entities, project_id="test_project")
    
    # Query all entities
    results = await mock_db_manager.query_entities(
        filters=None,
        limit=10,
        project_id="test_project"
    )
    assert len(results) == 2
    
    # Query by type
    results = await mock_db_manager.query_entities(
        filters={"type": "class"},
        limit=10,
        project_id="test_project"
    )
    assert len(results) == 1
    assert results[0]["name"] == "TestClass"


@pytest.mark.asyncio
async def test_query_relationships_method(mock_db_manager):
    """Test query_relationships convenience method."""
    
    # Add test relationships
    test_relationships = [
        {
            "id": "rel_1",
            "source_id": "entity_1",
            "target_id": "entity_2",
            "type": "calls",
            "project_id": "test_project",
        },
        {
            "id": "rel_2",
            "source_id": "entity_2",
            "target_id": "entity_3",
            "type": "imports",
            "project_id": "test_project",
        },
    ]
    
    await mock_db_manager.add_graph_relationships(test_relationships, project_id="test_project")
    
    # Query all relationships
    results = await mock_db_manager.query_relationships(
        filters=None,
        limit=10,
        project_id="test_project"
    )
    assert len(results) == 2
    
    # Query by source_id
    results = await mock_db_manager.query_relationships(
        filters={"source_id": "entity_1"},
        limit=10,
        project_id="test_project"
    )
    assert len(results) == 1
    assert results[0]["type"] == "calls"


@pytest.mark.asyncio
async def test_upsert_method(mock_db_manager):
    """Test upsert convenience method."""
    
    # Insert new records
    test_data = [
        {
            "id": "entity_1",
            "name": "TestClass",
            "type": "class",
            "file_path": "test.py",
            "project_id": "test_project",
        }
    ]
    
    await mock_db_manager.upsert(
        table_name="graph_entities",
        data=test_data,
        key_field="id"
    )
    
    # Verify insert
    results = await mock_db_manager.query_entities(
        filters={"id": "entity_1"},
        limit=1,
        project_id="test_project"
    )
    assert len(results) == 1
    assert results[0]["name"] == "TestClass"
    
    # Update existing record
    updated_data = [
        {
            "id": "entity_1",
            "name": "UpdatedClass",
            "type": "class",
            "file_path": "test.py",
            "project_id": "test_project",
        }
    ]
    
    await mock_db_manager.upsert(
        table_name="graph_entities",
        data=updated_data,
        key_field="id"
    )
    
    # Verify update
    results = await mock_db_manager.query_entities(
        filters={"id": "entity_1"},
        limit=1,
        project_id="test_project"
    )
    assert len(results) == 1
    assert results[0]["name"] == "UpdatedClass"
    
    # Test empty data (should be no-op)
    await mock_db_manager.upsert(
        table_name="graph_entities",
        data=[],
        key_field="id"
    )


# ============================================================================
# Schema Boundary Validation Tests (SDD-002)
# ============================================================================


@pytest.mark.asyncio
async def test_validate_record_rejects_forbidden_field_aliases(mock_db_manager):
    """Test that forbidden field aliases are rejected at write time."""
    
    # Test entity_id (should use 'id' instead)
    with pytest.raises(ValueError, match="entity_id.*not allowed.*Use 'id' instead"):
        mock_db_manager._validate_record(
            "graph_entities",
            {"entity_id": "test", "name": "Test", "type": "class"}
        )
    
    # Test chunk_id (should use 'id' instead)
    with pytest.raises(ValueError, match="chunk_id.*not allowed.*Use 'id' instead"):
        mock_db_manager._validate_record(
            "document_chunks",
            {"chunk_id": "test", "content": "Test"}
        )
    
    # Test relationship_type (should use 'type' instead)
    with pytest.raises(ValueError, match="relationship_type.*not allowed.*Use 'type' instead"):
        mock_db_manager._validate_record(
            "graph_relationships",
            {"relationship_type": "calls", "source_id": "a", "target_id": "b"}
        )
    
    # Test entity_type (should use 'type' instead)
    with pytest.raises(ValueError, match="entity_type.*not allowed.*Use 'type' instead"):
        mock_db_manager._validate_record(
            "graph_entities",
            {"entity_type": "class", "id": "test", "name": "Test"}
        )


@pytest.mark.asyncio
async def test_validate_record_rejects_missing_required_fields(mock_db_manager):
    """Test that missing required fields are detected at write time."""
    
    # Missing required fields for graph_entities
    with pytest.raises(ValueError, match="Missing required fields.*graph_entities"):
        mock_db_manager._validate_record(
            "graph_entities",
            {"name": "Test"}  # Missing: id, type, file_path, project_id
        )
    
    # Missing required fields for document_chunks
    with pytest.raises(ValueError, match="Missing required fields.*document_chunks"):
        mock_db_manager._validate_record(
            "document_chunks",
            {"content": "Test"}  # Missing: id, doc_id, file_path, project_id, content_type
        )
    
    # Missing required fields for graph_relationships
    with pytest.raises(ValueError, match="Missing required fields.*graph_relationships"):
        mock_db_manager._validate_record(
            "graph_relationships",
            {"type": "calls"}  # Missing: id, source_id, target_id, project_id
        )


@pytest.mark.asyncio
async def test_validate_record_accepts_valid_records(mock_db_manager):
    """Test that valid records pass validation."""
    
    # Valid graph entity
    mock_db_manager._validate_record(
        "graph_entities",
        {
            "id": "entity_1",
            "name": "TestClass",
            "type": "class",
            "file_path": "test.py",
            "project_id": "test_project"
        }
    )  # Should not raise
    
    # Valid document chunk
    mock_db_manager._validate_record(
        "document_chunks",
        {
            "id": "chunk_1",
            "doc_id": "doc_1",
            "file_path": "test.py",
            "project_id": "test_project",
            "content": "Test content",
            "content_type": "code"
        }
    )  # Should not raise
    
    # Valid graph relationship
    mock_db_manager._validate_record(
        "graph_relationships",
        {
            "id": "rel_1",
            "source_id": "entity_1",
            "target_id": "entity_2",
            "type": "calls",
            "project_id": "test_project"
        }
    )  # Should not raise


@pytest.mark.asyncio
async def test_add_rows_validates_before_write(mock_db_manager):
    """Test that _add_rows validates records before writing to database."""
    from agentic_inquiry.database.lancedb_manager import (
        FORBIDDEN_FIELD_ALIASES,
        REQUIRED_FIELDS,
    )
    
    # Verify constants are properly defined
    assert "entity_id" in FORBIDDEN_FIELD_ALIASES
    assert "chunk_id" in FORBIDDEN_FIELD_ALIASES
    assert "relationship_type" in FORBIDDEN_FIELD_ALIASES
    assert "entity_type" in FORBIDDEN_FIELD_ALIASES
    
    assert "graph_entities" in REQUIRED_FIELDS
    assert "document_chunks" in REQUIRED_FIELDS
    assert "graph_relationships" in REQUIRED_FIELDS
    
    # Attempt to write with forbidden field should fail
    with pytest.raises(ValueError, match="entity_id.*not allowed"):
        await mock_db_manager._add_rows(
            "graph_entities",
            [{"entity_id": "test", "name": "Test", "type": "class", "file_path": "t.py", "project_id": "p"}]
        )
