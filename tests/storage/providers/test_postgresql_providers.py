"""Integration tests for PostgreSQL storage providers.

These tests require PostgreSQL to be running with pgvector extension.
Run with: pytest -m postgres tests/storage/providers/test_postgresql_providers.py

To start PostgreSQL:
    docker-compose -f docker-compose.dev.yaml up -d
"""

import pytest
from typing import List

from agent_vault.models.document_chunk import DocumentChunk


# Mark all tests in this module as postgres integration tests
pytestmark = [pytest.mark.postgres, pytest.mark.integration]


class TestPostgresVectorProvider:
    """Integration tests for PostgresVectorProvider."""

    @pytest.fixture
    async def vector_provider(
        self, postgres_connection_manager, clean_postgres_tables
    ):
        """Create and initialize a vector provider for testing."""
        from agent_vault.storage.providers.postgresql import PostgresVectorProvider

        provider = PostgresVectorProvider(
            connection_manager=postgres_connection_manager,
            project_id="test-project",
            embedding_dim=384,
        )
        await provider.initialize()
        yield provider
        await provider.close()

    @pytest.fixture
    def sample_chunks(self) -> List[DocumentChunk]:
        """Create sample chunks for testing."""
        return [
            DocumentChunk(
                id="chunk-1",
                doc_id="doc-1",
                file_path="/test/file1.py",
                project_id="test-project",
                content="def hello(): return 'world'",
                fts_text="hello function returns world",
                vector=[0.1] * 384,
                content_type="CODE",
                language="python",
                metadata={"function": "hello"},
                chunk_index=0,  # First chunk in file1.py
            ),
            DocumentChunk(
                id="chunk-2",
                doc_id="doc-1",
                file_path="/test/file1.py",
                project_id="test-project",
                content="def goodbye(): return 'farewell'",
                fts_text="goodbye function returns farewell",
                vector=[0.2] * 384,
                content_type="CODE",
                language="python",
                metadata={"function": "goodbye"},
                chunk_index=1,  # Second chunk in file1.py
            ),
            DocumentChunk(
                id="chunk-3",
                doc_id="doc-2",
                file_path="/test/file2.js",
                project_id="test-project",
                content="function greet() { return 'hello'; }",
                fts_text="greet function returns hello",
                vector=[0.3] * 384,
                content_type="CODE",
                language="javascript",
                metadata={"function": "greet"},
                chunk_index=0,  # First chunk in file2.js
            ),
        ]

    async def test_initialize_creates_tables(self, vector_provider):
        """Test that initialize creates the required tables."""
        assert await vector_provider.table_exists("chunks")

    async def test_upsert_and_count(self, vector_provider, sample_chunks):
        """Test upserting chunks and counting them."""
        # Upsert chunks
        result = await vector_provider.upsert_chunks(sample_chunks, project_id="test-project")
        assert result == 3

        # Count chunks
        count = await vector_provider.count(project_id="test-project")
        assert count == 3

    async def test_upsert_idempotent(self, vector_provider, sample_chunks):
        """Test that upsert is idempotent."""
        # First upsert
        await vector_provider.upsert_chunks(sample_chunks, project_id="test-project")

        # Second upsert (same chunks)
        await vector_provider.upsert_chunks(sample_chunks, project_id="test-project")

        # Count should still be 3
        count = await vector_provider.count(project_id="test-project")
        assert count == 3

    async def test_get_chunks_by_file(self, vector_provider, sample_chunks):
        """Test retrieving chunks by file path."""
        await vector_provider.upsert_chunks(sample_chunks, project_id="test-project")

        chunks = await vector_provider.get_chunks_by_file("/test/file1.py", project_id="test-project")
        assert len(chunks) == 2
        assert all(c.file_path == "/test/file1.py" for c in chunks)

    async def test_delete_chunks_by_file(self, vector_provider, sample_chunks):
        """Test deleting chunks by file path."""
        await vector_provider.upsert_chunks(sample_chunks, project_id="test-project")

        deleted = await vector_provider.delete_chunks_by_file("/test/file1.py", project_id="test-project")
        assert deleted == 2

        count = await vector_provider.count(project_id="test-project")
        assert count == 1

    async def test_delete_chunks_by_ids(self, vector_provider, sample_chunks):
        """Test deleting chunks by IDs."""
        await vector_provider.upsert_chunks(sample_chunks, project_id="test-project")

        deleted = await vector_provider.delete_chunks_by_ids(["chunk-1", "chunk-3"], project_id="test-project")
        assert deleted == 2

        count = await vector_provider.count(project_id="test-project")
        assert count == 1

    async def test_vector_search(self, vector_provider, sample_chunks):
        """Test vector similarity search."""
        await vector_provider.upsert_chunks(sample_chunks, project_id="test-project")

        # Search with vector similar to chunk-1
        query_vector = [0.1] * 384
        results = await vector_provider.vector_search(
            query_vector=query_vector,
            limit=2,
            project_id="test-project",
        )

        assert len(results) <= 2
        # First result should be chunk-1 (exact match)
        assert results[0].id == "chunk-1"

    async def test_count_with_filter(self, vector_provider, sample_chunks):
        """Test counting chunks with filter."""
        await vector_provider.upsert_chunks(sample_chunks, project_id="test-project")

        # Count only Python files
        count = await vector_provider.count(
            filters={"file_path": "/test/file1.py"},
            project_id="test-project",
        )
        assert count == 2


class TestPostgresEventProvider:
    """Integration tests for PostgresEventProvider."""

    @pytest.fixture
    async def event_provider(
        self, postgres_connection_manager, clean_postgres_tables
    ):
        """Create and initialize an event provider for testing."""
        from agent_vault.storage.providers.postgresql import PostgresEventProvider

        provider = PostgresEventProvider(
            connection_manager=postgres_connection_manager,
            project_id="test-project",
        )
        await provider.initialize()
        yield provider
        await provider.close()

    async def test_initialize_creates_tables(self, event_provider):
        """Test that initialize creates the events table."""
        # If we get here without error, tables were created
        assert event_provider is not None

    async def test_write_and_query_events(self, event_provider):
        """Test writing and querying events."""
        from agent_vault.events.models import Event

        # Create test events
        events = [
            Event(
                event_id="evt-1",
                session_id="session-1",
                event_type="test.write_query",
                source="test",
                metadata={"tool": "read"},
            ),
            Event(
                event_id="evt-2",
                session_id="session-1",
                event_type="test.write_query",
                source="test",
                metadata={"result": "success"},
            ),
        ]

        # Write events
        await event_provider.write_events(events)

        # Query events by event_type
        results = await event_provider.query_events(event_type="test.write_query")
        assert len(results) == 2

    async def test_count_events(self, event_provider):
        """Test counting events."""
        from agent_vault.events.models import Event

        events = [
            Event(
                event_id=f"evt-{i}",
                session_id="session-1",
                event_type="test",
                source="test",
                metadata={},
            )
            for i in range(5)
        ]

        await event_provider.write_events(events)

        count = await event_provider.count_events()
        assert count == 5


class TestPostgresFileTrackerProvider:
    """Integration tests for PostgresFileTrackerProvider."""

    @pytest.fixture
    async def file_tracker(
        self, postgres_connection_manager, clean_postgres_tables
    ):
        """Create and initialize a file tracker provider for testing."""
        from agent_vault.storage.providers.postgresql import PostgresFileTrackerProvider

        provider = PostgresFileTrackerProvider(
            connection_manager=postgres_connection_manager,
            project_id="test-project",
        )
        await provider.initialize()
        yield provider
        await provider.close()

    async def test_update_and_get_hash(self, file_tracker):
        """Test updating and retrieving file hashes."""
        await file_tracker.update_hash("/test/file.py", "abc123")

        result = await file_tracker.get_hash("/test/file.py")
        assert result == "abc123"

    async def test_has_changed(self, file_tracker, tmp_path):
        """Test file change detection."""

        # Create a real file for testing
        test_file = tmp_path / "test_file.py"
        test_file.write_text("print('hello')")
        file_path = str(test_file)

        # First check - file not tracked yet, should return True
        changed = await file_tracker.has_changed(file_path)
        assert changed is True

        # Compute hash and store it
        import hashlib
        with open(file_path, 'rb') as f:
            current_hash = hashlib.sha256(f.read()).hexdigest()
        await file_tracker.update_hash(file_path, current_hash)

        # Same content - not changed
        changed = await file_tracker.has_changed(file_path)
        assert changed is False

        # Modify file content - should be changed
        test_file.write_text("print('modified')")
        changed = await file_tracker.has_changed(file_path)
        assert changed is True

    async def test_remove_file(self, file_tracker):
        """Test removing file from tracking."""
        await file_tracker.update_hash("/test/file.py", "abc123")

        removed = await file_tracker.remove_file("/test/file.py")
        assert removed is True

        result = await file_tracker.get_hash("/test/file.py")
        assert result is None

    async def test_list_tracked_files(self, file_tracker):
        """Test listing all tracked files."""
        await file_tracker.update_hash("/test/file1.py", "hash1")
        await file_tracker.update_hash("/test/file2.py", "hash2")
        await file_tracker.update_hash("/test/file3.py", "hash3")

        # Returns list of (file_path, content_hash) tuples
        files = await file_tracker.list_tracked_files()
        assert len(files) == 3

        # Extract just file paths for easier assertion
        file_paths = [f[0] for f in files]
        assert "/test/file1.py" in file_paths
        assert "/test/file2.py" in file_paths
        assert "/test/file3.py" in file_paths

        # Also verify hashes are returned correctly
        file_dict = dict(files)
        assert file_dict["/test/file1.py"] == "hash1"
        assert file_dict["/test/file2.py"] == "hash2"
        assert file_dict["/test/file3.py"] == "hash3"

    async def test_clear(self, file_tracker):
        """Test clearing all tracked files."""
        await file_tracker.update_hash("/test/file1.py", "hash1")
        await file_tracker.update_hash("/test/file2.py", "hash2")

        await file_tracker.clear()

        files = await file_tracker.list_tracked_files()
        assert len(files) == 0


class TestPostgresGraphProvider:
    """Integration tests for PostgresGraphProvider."""

    @pytest.fixture
    async def graph_provider(
        self, postgres_connection_manager, clean_postgres_tables
    ):
        """Create and initialize a graph provider for testing."""
        from agent_vault.storage.providers.postgresql import PostgresGraphProvider

        provider = PostgresGraphProvider(
            connection_manager=postgres_connection_manager,
            project_id="test-project",
        )
        await provider.initialize()
        yield provider
        await provider.close()

    @pytest.fixture
    def sample_entities(self) -> List:
        """Create sample entities for testing."""
        from agent_vault.models.graph_entity import GraphEntity

        return [
            GraphEntity(
                id="entity-1",
                name="hello",
                type="function",
                file_path="/test/file.py",
                doc_id="doc-1",
                project_id="test-project",
                vector=[0.1] * 384,
            ),
            GraphEntity(
                id="entity-2",
                name="goodbye",
                type="function",
                file_path="/test/file.py",
                doc_id="doc-1",
                project_id="test-project",
                vector=[0.2] * 384,
            ),
            GraphEntity(
                id="entity-3",
                name="helper",
                type="function",
                file_path="/test/file2.py",
                doc_id="doc-2",
                project_id="test-project",
                vector=[0.3] * 384,
            ),
        ]

    @pytest.fixture
    def sample_relationships(self) -> List:
        """Create sample relationships for testing."""
        from agent_vault.models.graph_relationship import GraphRelationship

        return [
            GraphRelationship(
                id="rel-1",
                source_id="entity-1",
                target_id="entity-2",
                type="calls",
                project_id="test-project",
                vector=[0.1] * 384,
            ),
            GraphRelationship(
                id="rel-2",
                source_id="entity-1",
                target_id="entity-3",
                type="calls",
                project_id="test-project",
                vector=[0.2] * 384,
            ),
        ]

    async def test_initialize_creates_tables(self, graph_provider):
        """Test that initialize creates the required tables."""
        # If we get here without error, tables were created
        assert graph_provider is not None

    async def test_upsert_and_get_entity(self, graph_provider, sample_entities):
        """Test upserting and retrieving entities."""
        # Upsert a single entity
        count = await graph_provider.upsert_entities([sample_entities[0]], project_id="test-project")
        assert count == 1

        # Retrieve by ID
        retrieved = await graph_provider.get_entity("entity-1", project_id="test-project")
        assert retrieved is not None
        assert retrieved.name == "hello"
        assert retrieved.type == "function"

    async def test_upsert_and_get_relationship(self, graph_provider, sample_entities, sample_relationships):
        """Test upserting and retrieving relationships."""
        # Create entities first
        await graph_provider.upsert_entities(sample_entities[:2], project_id="test-project")

        # Create relationship
        count = await graph_provider.upsert_relationships([sample_relationships[0]], project_id="test-project")
        assert count == 1

        # Retrieve relationships by entity
        rels = await graph_provider.get_relationships_by_entity(
            "entity-1", direction="outgoing", project_id="test-project"
        )
        assert len(rels) >= 1
        assert any(r.target_id == "entity-2" for r in rels)

    async def test_find_outgoing_relationships(self, graph_provider, sample_entities, sample_relationships):
        """Test finding outgoing relationships from an entity."""
        # Create all entities
        await graph_provider.upsert_entities(sample_entities, project_id="test-project")

        # Create all relationships
        await graph_provider.upsert_relationships(sample_relationships, project_id="test-project")

        # Find outgoing relationships
        rels = await graph_provider.get_relationships_by_entity(
            entity_id="entity-1",
            direction="outgoing",
            project_id="test-project",
        )
        assert len(rels) == 2
