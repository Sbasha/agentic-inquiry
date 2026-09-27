"""Contract tests for VectorStorageProtocol.

These tests verify that all vector storage providers correctly implement
the VectorStorageProtocol interface and behave consistently.

Each test is run against all provider implementations via the parameterized
`vector_provider` fixture.
"""

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contracts]


class TestVectorStorageLifecycle:
    """Tests for provider lifecycle management."""

    @pytest.mark.asyncio
    async def test_is_initialized_after_init(self, vector_provider):
        """Provider should be initialized after initialize() is called."""
        # The fixture already called initialize()
        assert vector_provider.is_initialized is True

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self, vector_provider):
        """Multiple calls to initialize() should be safe."""
        # Already initialized by fixture
        await vector_provider.initialize()
        await vector_provider.initialize()
        assert vector_provider.is_initialized is True

    @pytest.mark.asyncio
    async def test_close_marks_not_initialized(self, vector_provider, project_id):
        """After close(), provider should not be initialized."""
        await vector_provider.close()
        assert vector_provider.is_initialized is False

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, vector_provider):
        """Multiple calls to close() should be safe."""
        await vector_provider.close()
        await vector_provider.close()
        assert vector_provider.is_initialized is False


class TestChunkCRUD:
    """Tests for chunk CRUD operations."""

    @pytest.mark.asyncio
    async def test_upsert_chunks_returns_count(
        self, vector_provider, project_id, chunk_factory
    ):
        """upsert_chunks should return the number of chunks upserted."""
        chunks = [
            chunk_factory(chunk_id="c1", project_id=project_id),
            chunk_factory(chunk_id="c2", project_id=project_id),
        ]

        count = await vector_provider.upsert_chunks(chunks, project_id)

        assert count == 2

    @pytest.mark.asyncio
    async def test_upsert_chunks_updates_existing(
        self, vector_provider, project_id, chunk_factory
    ):
        """upsert_chunks should update existing chunks."""
        chunk = chunk_factory(chunk_id="c1", project_id=project_id, content="original")
        await vector_provider.upsert_chunks([chunk], project_id)

        # Update with new content
        updated = chunk_factory(chunk_id="c1", project_id=project_id, content="updated")
        count = await vector_provider.upsert_chunks([updated], project_id)

        assert count == 1
        # Verify the update
        retrieved = await vector_provider.get_chunks_by_file(
            chunk.file_path, project_id
        )
        assert len(retrieved) == 1
        assert retrieved[0].content == "updated"

    @pytest.mark.asyncio
    async def test_get_chunks_by_file_returns_empty_for_nonexistent(
        self, vector_provider, project_id
    ):
        """get_chunks_by_file should return empty list for non-existent file."""
        result = await vector_provider.get_chunks_by_file("/nonexistent.py", project_id)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_chunks_by_file_returns_matching(
        self, vector_provider, project_id, chunk_factory
    ):
        """get_chunks_by_file should return chunks from the specified file."""
        file1 = "/test/file1.py"
        file2 = "/test/file2.py"

        chunks = [
            chunk_factory(chunk_id="c1", project_id=project_id, file_path=file1),
            chunk_factory(chunk_id="c2", project_id=project_id, file_path=file1),
            chunk_factory(chunk_id="c3", project_id=project_id, file_path=file2),
        ]
        await vector_provider.upsert_chunks(chunks, project_id)

        result = await vector_provider.get_chunks_by_file(file1, project_id)

        assert len(result) == 2
        assert all(c.file_path == file1 for c in result)

    @pytest.mark.asyncio
    async def test_delete_chunks_by_file_returns_count(
        self, vector_provider, project_id, chunk_factory
    ):
        """delete_chunks_by_file should return number of deleted chunks."""
        file_path = "/test/delete_me.py"
        chunks = [
            chunk_factory(chunk_id="c1", project_id=project_id, file_path=file_path),
            chunk_factory(chunk_id="c2", project_id=project_id, file_path=file_path),
        ]
        await vector_provider.upsert_chunks(chunks, project_id)

        deleted = await vector_provider.delete_chunks_by_file(file_path, project_id)

        assert deleted == 2

    @pytest.mark.asyncio
    async def test_delete_chunks_by_file_removes_chunks(
        self, vector_provider, project_id, chunk_factory
    ):
        """delete_chunks_by_file should remove chunks from storage."""
        file_path = "/test/delete_me.py"
        chunks = [
            chunk_factory(chunk_id="c1", project_id=project_id, file_path=file_path),
        ]
        await vector_provider.upsert_chunks(chunks, project_id)

        await vector_provider.delete_chunks_by_file(file_path, project_id)

        result = await vector_provider.get_chunks_by_file(file_path, project_id)
        assert result == []

    @pytest.mark.asyncio
    async def test_delete_chunks_by_ids_returns_count(
        self, vector_provider, project_id, chunk_factory
    ):
        """delete_chunks_by_ids should return number of deleted chunks."""
        chunks = [
            chunk_factory(chunk_id="c1", project_id=project_id),
            chunk_factory(chunk_id="c2", project_id=project_id),
            chunk_factory(chunk_id="c3", project_id=project_id),
        ]
        await vector_provider.upsert_chunks(chunks, project_id)

        deleted = await vector_provider.delete_chunks_by_ids(["c1", "c2"], project_id)

        assert deleted == 2


class TestVectorSearch:
    """Tests for vector search operations."""

    @pytest.mark.asyncio
    async def test_vector_search_returns_results(
        self, vector_provider, project_id, chunk_factory
    ):
        """vector_search should return matching results."""
        chunks = [
            chunk_factory(
                chunk_id="c1",
                project_id=project_id,
                vector=[0.9] * 384,
            ),
            chunk_factory(
                chunk_id="c2",
                project_id=project_id,
                vector=[0.1] * 384,
            ),
        ]
        await vector_provider.upsert_chunks(chunks, project_id)

        # Search with vector similar to first chunk
        query_vector = [0.9] * 384
        results = await vector_provider.vector_search(
            query_vector, limit=10, project_id=project_id
        )

        assert len(results) >= 1
        # First result should be most similar
        assert results[0].id == "c1"

    @pytest.mark.asyncio
    async def test_vector_search_respects_limit(
        self, vector_provider, project_id, chunk_factory
    ):
        """vector_search should respect the limit parameter."""
        chunks = [
            chunk_factory(chunk_id=f"c{i}", project_id=project_id) for i in range(10)
        ]
        await vector_provider.upsert_chunks(chunks, project_id)

        results = await vector_provider.vector_search(
            [0.1] * 384, limit=3, project_id=project_id
        )

        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_vector_search_returns_empty_for_empty_storage(
        self, vector_provider, project_id
    ):
        """vector_search should return empty list when storage is empty."""
        results = await vector_provider.vector_search(
            [0.1] * 384, limit=10, project_id=project_id
        )

        assert results == []


class TestFullTextSearch:
    """Tests for full-text search operations."""

    @pytest.mark.asyncio
    async def test_fts_search_returns_results(
        self, vector_provider, project_id, chunk_factory
    ):
        """fts_search should return matching results."""
        chunks = [
            chunk_factory(
                chunk_id="c1",
                project_id=project_id,
                content="authentication login security",
            ),
            chunk_factory(
                chunk_id="c2",
                project_id=project_id,
                content="database query optimization",
            ),
        ]
        await vector_provider.upsert_chunks(chunks, project_id)

        results = await vector_provider.fts_search(
            "authentication", limit=10, project_id=project_id
        )

        assert len(results) >= 1
        assert results[0].id == "c1"

    @pytest.mark.asyncio
    async def test_fts_search_returns_empty_for_no_match(
        self, vector_provider, project_id, chunk_factory
    ):
        """fts_search should return empty list when no content matches."""
        chunks = [
            chunk_factory(
                chunk_id="c1",
                project_id=project_id,
                content="hello world",
            ),
        ]
        await vector_provider.upsert_chunks(chunks, project_id)

        results = await vector_provider.fts_search(
            "xyznonexistent", limit=10, project_id=project_id
        )

        assert results == []


class TestHybridSearch:
    """Tests for hybrid search operations."""

    @pytest.mark.asyncio
    async def test_hybrid_search_returns_results(
        self, vector_provider, project_id, chunk_factory
    ):
        """hybrid_search should return combined results."""
        chunks = [
            chunk_factory(
                chunk_id="c1",
                project_id=project_id,
                content="authentication login",
                vector=[0.9] * 384,
            ),
            chunk_factory(
                chunk_id="c2",
                project_id=project_id,
                content="database query",
                vector=[0.1] * 384,
            ),
        ]
        await vector_provider.upsert_chunks(chunks, project_id)

        results = await vector_provider.hybrid_search(
            query_vector=[0.9] * 384,
            query_text="authentication",
            limit=10,
            project_id=project_id,
        )

        assert len(results) >= 1


class TestQueryOperations:
    """Tests for query operations."""

    @pytest.mark.asyncio
    async def test_query_with_filters(self, vector_provider, project_id, chunk_factory):
        """query should return chunks matching filters."""
        chunks = [
            chunk_factory(
                chunk_id="c1",
                project_id=project_id,
                file_path="/test/a.py",
            ),
            chunk_factory(
                chunk_id="c2",
                project_id=project_id,
                file_path="/test/b.py",
            ),
        ]
        await vector_provider.upsert_chunks(chunks, project_id)

        results = await vector_provider.query(
            filters={"file_path": "/test/a.py"},
            project_id=project_id,
        )

        assert len(results) == 1
        assert results[0].file_path == "/test/a.py"

    @pytest.mark.asyncio
    async def test_count_returns_total(
        self, vector_provider, project_id, chunk_factory
    ):
        """count should return total number of matching chunks."""
        chunks = [
            chunk_factory(chunk_id=f"c{i}", project_id=project_id) for i in range(5)
        ]
        await vector_provider.upsert_chunks(chunks, project_id)

        total = await vector_provider.count(project_id=project_id)

        assert total == 5

    @pytest.mark.asyncio
    async def test_count_with_filters(self, vector_provider, project_id, chunk_factory):
        """count should respect filters."""
        chunks = [
            chunk_factory(
                chunk_id="c1",
                project_id=project_id,
                content_type="CODE",
            ),
            chunk_factory(
                chunk_id="c2",
                project_id=project_id,
                content_type="PROSE",  # Use valid content_type
            ),
        ]
        await vector_provider.upsert_chunks(chunks, project_id)

        code_count = await vector_provider.count(
            filters={"content_type": "CODE"},
            project_id=project_id,
        )

        assert code_count == 1


class TestTableOperations:
    """Tests for table management operations."""

    @pytest.mark.asyncio
    async def test_list_tables_returns_list(self, vector_provider):
        """list_tables should return a list of table names."""
        tables = await vector_provider.list_tables()

        assert isinstance(tables, list)
        # Note: LanceDB creates tables lazily, so the list may be empty
        # until data is inserted. We just verify it's a list.

    @pytest.mark.asyncio
    async def test_table_exists_after_data_insertion(
        self, vector_provider, project_id, chunk_factory
    ):
        """table_exists should return True for document_chunks table after data is inserted."""
        # Insert some data to ensure table exists
        chunk = chunk_factory(chunk_id="table_test", project_id=project_id)
        await vector_provider.upsert_chunks([chunk], project_id)

        exists = await vector_provider.table_exists("document_chunks")
        assert exists is True

    @pytest.mark.asyncio
    async def test_table_exists_for_nonexistent(self, vector_provider):
        """table_exists should return False for non-existent table."""
        exists = await vector_provider.table_exists("nonexistent_table_xyz")

        assert exists is False


class TestMaintenanceOperations:
    """Tests for maintenance operations (if supported)."""

    @pytest.mark.asyncio
    async def test_health_check_returns_status(self, vector_provider):
        """health_check should return a dict with status."""
        health = await vector_provider.health_check()

        assert isinstance(health, dict)
        assert "status" in health

    @pytest.mark.asyncio
    async def test_health_check_healthy_when_initialized(self, vector_provider):
        """health_check should return healthy status when initialized."""
        health = await vector_provider.health_check()

        assert health["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_run_maintenance_returns_result(self, vector_provider, project_id):
        """run_maintenance should return maintenance result."""
        result = await vector_provider.run_maintenance(project_id)

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_validate_integrity_returns_result(self, vector_provider, project_id):
        """validate_integrity should return validation result."""
        result = await vector_provider.validate_integrity(project_id)

        assert isinstance(result, dict)


class TestProjectIsolation:
    """Tests for project-based data isolation."""

    @pytest.mark.asyncio
    async def test_chunks_isolated_by_project(self, vector_provider, chunk_factory):
        """Chunks from different projects should be isolated."""
        project_a = "project_a_test"
        project_b = "project_b_test"

        chunk_a = chunk_factory(chunk_id="ca", project_id=project_a)
        chunk_b = chunk_factory(chunk_id="cb", project_id=project_b)

        await vector_provider.upsert_chunks([chunk_a], project_a)
        await vector_provider.upsert_chunks([chunk_b], project_b)

        count_a = await vector_provider.count(project_id=project_a)
        count_b = await vector_provider.count(project_id=project_b)

        assert count_a == 1
        assert count_b == 1

    @pytest.mark.asyncio
    async def test_vector_search_respects_project(self, vector_provider, chunk_factory):
        """vector_search should only return results from specified project."""
        project_a = "project_a_search"
        project_b = "project_b_search"

        chunk_a = chunk_factory(chunk_id="ca", project_id=project_a)
        chunk_b = chunk_factory(chunk_id="cb", project_id=project_b)

        await vector_provider.upsert_chunks([chunk_a], project_a)
        await vector_provider.upsert_chunks([chunk_b], project_b)

        results = await vector_provider.vector_search(
            [0.1] * 384, limit=10, project_id=project_a
        )

        # Should only find chunk from project_a
        result_ids = [r.id for r in results]
        assert "ca" in result_ids
        assert "cb" not in result_ids
