"""Unit tests for PostgreSQL storage providers with mocked asyncpg.

These tests verify the SQL generation and logic of PostgreSQL providers
without requiring a real PostgreSQL database.

Run with: pytest tests/storage/providers/test_postgresql_providers_unit.py -v
"""

import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Mark all tests in this module as unit tests
pytestmark = [pytest.mark.unit]


# =============================================================================
# Mock Helpers
# =============================================================================


class MockRecord(dict):
    """Mock asyncpg.Record that supports both dict and attribute access."""

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"'MockRecord' has no attribute '{key}'")

    def get(self, key: str, default: Any = None) -> Any:
        return super().get(key, default)


def make_record(**kwargs) -> MockRecord:
    """Create a mock record with the given fields."""
    return MockRecord(kwargs)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_connection_manager():
    """Create a mock PostgresConnectionManager."""
    manager = MagicMock()
    manager.connection_string = "postgresql://test:test@localhost/testdb"
    manager.table_prefix = "agv_test_"
    manager.similarity_metric = "cosine"
    manager.is_initialized = True
    manager._initialized = True

    # Mock async methods
    manager.initialize = AsyncMock()
    manager.close = AsyncMock()
    manager.execute = AsyncMock(return_value="OK")
    manager.fetch = AsyncMock(return_value=[])
    manager.fetchrow = AsyncMock(return_value=None)
    manager.fetchval = AsyncMock(return_value=None)
    manager.executemany = AsyncMock()
    manager.ensure_extension = AsyncMock()

    # Mock connection for context managers
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value="OK")
    mock_conn.executemany = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value=None)
    # Return None for dimension check (indicates table doesn't exist or column not found)
    mock_conn.fetchval = AsyncMock(return_value=None)

    # Mock transaction context manager (explicit assignment pattern)
    mock_transaction_ctx = AsyncMock()
    mock_transaction_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_transaction_ctx.__aexit__ = AsyncMock(return_value=None)
    manager.transaction = MagicMock(return_value=mock_transaction_ctx)

    # Mock acquire context manager (explicit assignment pattern)
    mock_acquire_ctx = AsyncMock()
    mock_acquire_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire_ctx.__aexit__ = AsyncMock(return_value=None)
    manager.acquire = MagicMock(return_value=mock_acquire_ctx)

    return manager


@pytest.fixture
def mock_conn(mock_connection_manager):
    """Get the mock connection from the manager."""
    return mock_connection_manager.transaction.return_value.__aenter__.return_value


# =============================================================================
# PostgresVectorProvider Tests
# =============================================================================


class TestPostgresVectorProviderUnit:
    """Unit tests for PostgresVectorProvider with mocked asyncpg."""

    @pytest.fixture
    def vector_provider(self, mock_connection_manager):
        """Create a vector provider with mocked connection."""
        from agent_vault.storage.providers.postgresql import PostgresVectorProvider

        provider = PostgresVectorProvider(
            connection_manager=mock_connection_manager,
            project_id="test-project",
            embedding_dim=384,
        )
        provider._initialized = True
        return provider

    async def test_initialize_creates_extension_and_tables(self, mock_connection_manager):
        """Test that initialize creates pgvector extension and tables."""
        from agent_vault.storage.providers.postgresql import PostgresVectorProvider

        provider = PostgresVectorProvider(
            connection_manager=mock_connection_manager,
            project_id="test-project",
            embedding_dim=384,
        )

        await provider.initialize()

        # Should ensure pgvector extension
        mock_connection_manager.ensure_extension.assert_called_once_with("vector")
        # Should execute CREATE TABLE statements
        assert mock_connection_manager.execute.call_count > 0

    async def test_upsert_chunks_generates_correct_sql(self, vector_provider, mock_conn):
        """Test that upsert_chunks generates correct INSERT ON CONFLICT SQL."""
        from agent_vault.models.document_chunk import DocumentChunk

        chunks = [
            DocumentChunk(
                id="chunk-1",
                doc_id="doc-1",
                file_path="/test/file.py",
                project_id="test-project",
                content="def hello(): pass",
                fts_text="hello function",
                vector=[0.1] * 384,
                content_type="CODE",
                language="python",
                metadata={"key": "value"},
            )
        ]

        result = await vector_provider.upsert_chunks(chunks, "test-project")

        assert result == 1
        # Verify executemany was called (batch INSERT for chunks and FTS)
        assert mock_conn.executemany.call_count >= 2

    async def test_upsert_chunks_validates_project_id(self, vector_provider):
        """Test that upsert_chunks raises on project_id mismatch."""
        from agent_vault.models.document_chunk import DocumentChunk

        chunks = [
            DocumentChunk(
                id="chunk-1",
                doc_id="doc-1",
                file_path="/test/file.py",
                project_id="wrong-project",  # Mismatch with "test-project"
                content="test",
                fts_text="test",
                vector=[0.1] * 384,
                content_type="CODE",
            )
        ]

        # Should raise ValueError due to project_id mismatch
        with pytest.raises(ValueError, match="project_id mismatch"):
            await vector_provider.upsert_chunks(chunks, "test-project")

    async def test_upsert_empty_chunks_returns_zero(self, vector_provider):
        """Test that upserting empty list returns 0."""
        result = await vector_provider.upsert_chunks([], "test-project")
        assert result == 0

    async def test_delete_chunks_by_file_parses_result(self, vector_provider, mock_connection_manager):
        """Test that delete_chunks_by_file correctly parses DELETE result."""
        mock_connection_manager.execute.return_value = "DELETE 5"

        result = await vector_provider.delete_chunks_by_file("/test/file.py", "test-project")

        assert result == 5
        # Verify the SQL contains correct WHERE clause
        call_args = mock_connection_manager.execute.call_args
        assert "DELETE FROM" in call_args[0][0]
        assert "test-project" in call_args[0]
        assert "/test/file.py" in call_args[0]

    async def test_delete_chunks_by_ids_handles_empty_list(self, vector_provider):
        """Test that delete_chunks_by_ids handles empty list."""
        result = await vector_provider.delete_chunks_by_ids([], "test-project")
        assert result == 0

    async def test_vector_search_builds_correct_query(self, vector_provider, mock_connection_manager):
        """Test that vector_search builds correct pgvector query."""
        mock_connection_manager.fetch.return_value = [
            make_record(
                id="chunk-1",
                doc_id="doc-1",
                file_path="/test.py",
                project_id="test-project",
                content="test",
                content_type="CODE",
                metadata="{}",
                embedding=[0.1] * 384,
                similarity=0.95,
            )
        ]

        query_vector = [0.1] * 384
        results = await vector_provider.vector_search(query_vector, limit=10)

        assert len(results) == 1
        assert results[0].score == pytest.approx(0.95, rel=0.01)
        # Verify pgvector operator was used
        call_args = mock_connection_manager.fetch.call_args
        assert "<=>" in call_args[0][0]  # pgvector cosine distance operator

    async def test_fts_search_builds_correct_query(self, vector_provider, mock_connection_manager):
        """Test that fts_search uses PostgreSQL FTS operators."""
        mock_connection_manager.fetch.return_value = [
            make_record(
                id="chunk-1",
                doc_id="doc-1",
                file_path="/test.py",
                project_id="test-project",
                content="test content",
                content_type="CODE",
                metadata="{}",
                embedding=[],
                rank=0.8,
            )
        ]

        results = await vector_provider.fts_search("test query", limit=10)

        assert len(results) == 1
        # Verify FTS operators used
        call_args = mock_connection_manager.fetch.call_args
        sql = call_args[0][0]
        assert "plainto_tsquery" in sql
        assert "@@" in sql
        assert "ts_rank" in sql

    async def test_count_with_filters(self, vector_provider, mock_connection_manager):
        """Test count with filters builds correct WHERE clause."""
        mock_connection_manager.fetchval.return_value = 42

        result = await vector_provider.count(
            filters={"file_path": "/test.py"},
            project_id="test-project"
        )

        assert result == 42
        call_args = mock_connection_manager.fetchval.call_args
        sql = call_args[0][0]
        assert "COUNT(*)" in sql
        assert "file_path" in sql

    async def test_table_exists_checks_information_schema(self, vector_provider, mock_connection_manager):
        """Test that table_exists queries information_schema."""
        mock_connection_manager.fetchval.return_value = True

        result = await vector_provider.table_exists("chunks")

        assert result is True
        call_args = mock_connection_manager.fetchval.call_args
        assert "information_schema.tables" in call_args[0][0]


# =============================================================================
# PostgresGraphProvider Tests
# =============================================================================


class TestPostgresGraphProviderUnit:
    """Unit tests for PostgresGraphProvider with mocked asyncpg."""

    @pytest.fixture
    def graph_provider(self, mock_connection_manager):
        """Create a graph provider with mocked connection."""
        from agent_vault.storage.providers.postgresql import PostgresGraphProvider

        provider = PostgresGraphProvider(
            connection_manager=mock_connection_manager,
            project_id="test-project",
            embedding_dim=384,
        )
        provider._initialized = True
        return provider

    async def test_upsert_entities_generates_correct_sql(self, graph_provider, mock_conn):
        """Test that upsert_entities generates correct INSERT ON CONFLICT SQL via batch."""
        from agent_vault.models.graph_entity import GraphEntity

        entities = [
            GraphEntity(
                id="entity-1",
                name="TestClass",
                type="class",
                file_path="/test/file.py",
                doc_id="doc-1",
                project_id="test-project",
                vector=[0.1] * 384,
            )
        ]

        result = await graph_provider.upsert_entities(entities, "test-project")

        assert result == 1
        # Batch insert uses executemany instead of execute
        call_args = mock_conn.executemany.call_args
        sql = call_args[0][0]
        assert "INSERT INTO" in sql
        assert "ON CONFLICT" in sql
        assert "DO UPDATE" in sql
        # Verify batch params were passed
        batch_params = call_args[0][1]
        assert len(batch_params) == 1  # One entity in batch

    async def test_get_entity_returns_none_when_not_found(self, graph_provider, mock_connection_manager):
        """Test that get_entity returns None when entity not found."""
        mock_connection_manager.fetchrow.return_value = None

        result = await graph_provider.get_entity("nonexistent", "test-project")

        assert result is None

    async def test_get_entity_converts_row_to_entity(self, graph_provider, mock_connection_manager):
        """Test that get_entity correctly converts database row."""
        mock_connection_manager.fetchrow.return_value = make_record(
            id="entity-1",
            name="TestClass",
            entity_type="class",
            file_path="/test/file.py",
            project_id="test-project",
            start_line=10,
            end_line=50,
            embedding=[0.1] * 384,
            metadata=json.dumps({"doc_id": "doc-1", "pagerank": 0.5}),
        )

        result = await graph_provider.get_entity("entity-1", "test-project")

        assert result is not None
        assert result.id == "entity-1"
        assert result.name == "TestClass"
        assert result.type == "class"
        assert result.pagerank == 0.5

    async def test_get_neighbors_uses_recursive_cte(self, graph_provider, mock_connection_manager):
        """Test that get_neighbors uses recursive CTE for graph traversal."""
        mock_connection_manager.fetch.return_value = []

        await graph_provider.get_neighbors(
            entity_id="entity-1",
            direction="outgoing",
            depth=2,
            project_id="test-project",
        )

        call_args = mock_connection_manager.fetch.call_args
        sql = call_args[0][0]
        assert "WITH RECURSIVE" in sql
        assert "UNION" in sql

    async def test_upsert_relationships_handles_conflict(self, graph_provider, mock_conn):
        """Test that upsert_relationships uses ON CONFLICT via batch."""
        from agent_vault.models.graph_relationship import GraphRelationship

        relationships = [
            GraphRelationship(
                id="rel-1",
                source_id="entity-1",
                target_id="entity-2",
                type="calls",
                project_id="test-project",
                vector=[],
            )
        ]

        result = await graph_provider.upsert_relationships(relationships, "test-project")

        assert result == 1
        # Batch insert uses executemany instead of execute
        call_args = mock_conn.executemany.call_args
        sql = call_args[0][0]
        assert "ON CONFLICT" in sql
        # Verify batch params were passed
        batch_params = call_args[0][1]
        assert len(batch_params) == 1  # One relationship in batch

    async def test_count_entities_with_filters(self, graph_provider, mock_connection_manager):
        """Test count_entities with type filter."""
        mock_connection_manager.fetchval.return_value = 10

        result = await graph_provider.count_entities(
            filters={"type": "function"},
            project_id="test-project"
        )

        assert result == 10
        call_args = mock_connection_manager.fetchval.call_args
        sql = call_args[0][0]
        assert "entity_type" in sql  # type is mapped to entity_type column


# =============================================================================
# PostgresGraphProvider Filter AST Tests
# =============================================================================


class TestPostgresGraphProviderFilterAST:
    """Test Filter AST handling in PostgresGraphProvider.

    The graph provider delegates to
    :class:`agent_vault.database.filters.PostgresFilterAdapter` — these
    tests exercise the public ``_build_filter_clause`` shim. Assertions
    reflect the adapter's output format: single conditions emit
    ``AND <expr>`` (no outer parens), compound nodes wrap with ``(...)``,
    and ``type`` is mapped to ``entity_type`` via the adapter's
    ``field_map`` parameter.
    """

    @pytest.fixture
    def graph_provider(self, mock_connection_manager):
        """Create a graph provider with mocked connection."""
        from agent_vault.storage.providers.postgresql import PostgresGraphProvider

        provider = PostgresGraphProvider(
            connection_manager=mock_connection_manager,
            project_id="test-project",
            embedding_dim=384,
        )
        provider._initialized = True
        return provider

    def test_simple_eq_maps_type_to_entity_type(self, graph_provider):
        from agent_vault.database.filters import eq

        clause, params = graph_provider._build_filter_clause(
            eq("type", "class"), param_offset=1
        )
        assert clause == " AND entity_type = $2"
        assert params == ["class"]

    def test_eq_unmapped_field_passes_through(self, graph_provider):
        from agent_vault.database.filters import eq

        clause, params = graph_provider._build_filter_clause(
            eq("name", "TestClass"), param_offset=1
        )
        assert clause == " AND name = $2"
        assert params == ["TestClass"]

    def test_and_compound(self, graph_provider):
        from agent_vault.database.filters import and_, eq

        clause, params = graph_provider._build_filter_clause(
            and_(eq("type", "class"), eq("name", "Foo")), param_offset=1
        )
        assert clause == " AND (entity_type = $2 AND name = $3)"
        assert params == ["class", "Foo"]

    def test_or_compound(self, graph_provider):
        from agent_vault.database.filters import eq, or_

        clause, params = graph_provider._build_filter_clause(
            or_(eq("type", "class"), eq("type", "function")), param_offset=1
        )
        assert clause == " AND (entity_type = $2 OR entity_type = $3)"
        assert params == ["class", "function"]

    def test_nested_compound(self, graph_provider):
        from agent_vault.database.filters import and_, eq, or_

        filter_ast = and_(
            or_(eq("type", "class"), eq("type", "function")),
            eq("name", "Foo"),
        )
        clause, params = graph_provider._build_filter_clause(
            filter_ast, param_offset=1
        )
        assert clause == (
            " AND ((entity_type = $2 OR entity_type = $3) AND name = $4)"
        )
        assert params == ["class", "function", "Foo"]

    def test_in_uses_positional_placeholders(self, graph_provider):
        """New adapter emits ``IN ($2, $3, $4)`` rather than ``= ANY($2)``.

        Semantically identical; just a different parameterization shape.
        The switch removes the need for asyncpg array-binding and keeps
        the SQL portable to other Postgres-dialect drivers.
        """
        from agent_vault.database.filters import is_in

        clause, params = graph_provider._build_filter_clause(
            is_in("type", ["class", "function", "method"]), param_offset=1
        )
        assert clause == " AND entity_type IN ($2, $3, $4)"
        assert params == ["class", "function", "method"]

    def test_not_in_uses_positional_placeholders(self, graph_provider):
        from agent_vault.database.filters import not_in

        clause, params = graph_provider._build_filter_clause(
            not_in("type", ["test", "fixture"]), param_offset=1
        )
        assert clause == " AND entity_type NOT IN ($2, $3)"
        assert params == ["test", "fixture"]

    def test_empty_in_is_false(self, graph_provider):
        from agent_vault.database.filters import is_in

        clause, params = graph_provider._build_filter_clause(
            is_in("type", []), param_offset=1
        )
        assert clause == " AND FALSE"
        assert params == []

    def test_empty_not_in_is_true(self, graph_provider):
        from agent_vault.database.filters import not_in

        clause, params = graph_provider._build_filter_clause(
            not_in("type", []), param_offset=1
        )
        assert clause == " AND TRUE"
        assert params == []

    def test_is_null(self, graph_provider):
        from agent_vault.database.filters import is_null

        clause, params = graph_provider._build_filter_clause(
            is_null("deleted_at"), param_offset=1
        )
        assert clause == " AND deleted_at IS NULL"
        assert params == []

    def test_is_not_null(self, graph_provider):
        from agent_vault.database.filters import is_not_null

        clause, params = graph_provider._build_filter_clause(
            is_not_null("embedding"), param_offset=1
        )
        assert clause == " AND embedding IS NOT NULL"
        assert params == []

    def test_comparison_operators(self, graph_provider):
        from agent_vault.database.filters import gt, gte, lt, lte, ne

        cases = [
            (ne("status", "deleted"), " AND status != $1", ["deleted"]),
            (gt("score", 0.5), " AND score > $1", [0.5]),
            (gte("rank", 10), " AND rank >= $1", [10]),
            (lt("depth", 5), " AND depth < $1", [5]),
            (lte("level", 3), " AND level <= $1", [3]),
        ]
        for node, expected_clause, expected_params in cases:
            clause, params = graph_provider._build_filter_clause(
                node, param_offset=0
            )
            assert clause == expected_clause
            assert params == expected_params

    def test_dotted_field_raises(self, graph_provider):
        """Postgres adapter rejects dotted fields (needs JSON operators)."""
        from agent_vault.database.filters import eq

        with pytest.raises(ValueError, match="Dotted field names"):
            graph_provider._build_filter_clause(
                eq("metadata.foo", "bar"), param_offset=1
            )

    def test_dict_backward_compat(self, graph_provider):
        clause, params = graph_provider._build_filter_clause(
            {"type": "function", "name": "main"}, param_offset=1
        )
        assert "entity_type = $2" in clause
        assert "name = $3" in clause
        assert params == ["function", "main"]

    def test_empty_filters_return_empty_clause(self, graph_provider):
        for empty in (None, {}):
            clause, params = graph_provider._build_filter_clause(empty)
            assert clause == ""
            assert params == []

    def test_param_offset_respected(self, graph_provider):
        from agent_vault.database.filters import eq

        clause, params = graph_provider._build_filter_clause(
            eq("type", "class"), param_offset=3
        )
        assert clause == " AND entity_type = $4"
        assert params == ["class"]

    def test_relationship_field_map_reroutes_type_column(self, graph_provider):
        """AST ``eq("type", ...)`` passed with the relationship field_map
        must hit the ``relationship_type`` column. Without an explicit
        field_map the default (entity) map would silently rewrite it to
        ``entity_type``, which doesn't exist on the relationships table.
        """
        from agent_vault.database.filters import eq

        clause, params = graph_provider._build_filter_clause(
            eq("type", "CALLS"),
            param_offset=1,
            field_map=graph_provider._RELATIONSHIP_COLUMN_MAP,
        )
        assert clause == " AND relationship_type = $2"
        assert params == ["CALLS"]

    def test_dict_relationship_type_with_relationship_field_map(
        self, graph_provider
    ):
        """Dict filters also honour the field_map argument."""
        clause, params = graph_provider._build_filter_clause(
            {"type": "CALLS"},
            param_offset=1,
            field_map=graph_provider._RELATIONSHIP_COLUMN_MAP,
        )
        assert clause == " AND relationship_type = $2"
        assert params == ["CALLS"]


# =============================================================================
# PostgresEventProvider Tests
# =============================================================================


class TestPostgresEventProviderUnit:
    """Unit tests for PostgresEventProvider with mocked asyncpg."""

    @pytest.fixture
    def event_provider(self, mock_connection_manager):
        """Create an event provider with mocked connection."""
        from agent_vault.storage.providers.postgresql import PostgresEventProvider

        provider = PostgresEventProvider(
            connection_manager=mock_connection_manager,
            project_id="test-project",
        )
        provider._initialized = True
        return provider

    async def test_write_events_maps_status_to_severity(self, event_provider, mock_connection_manager):
        """Test that write_events correctly maps EventStatus to severity."""
        from agent_vault.events.models import Event, EventStatus

        events = [
            Event(
                event_id="evt-1",
                project_id="test-project",
                event_type="indexing.started",
                status=EventStatus.STARTED,
                source="test",
                metadata={"message": "Starting"},
            ),
            Event(
                event_id="evt-2",
                project_id="test-project",
                event_type="indexing.failed",
                status=EventStatus.FAILED,
                source="test",
                metadata={"message": "Error occurred"},
            ),
        ]

        # Mock the transaction context
        mock_conn = AsyncMock()
        mock_conn.executemany = AsyncMock()
        mock_connection_manager.transaction.return_value.__aenter__.return_value = mock_conn

        result = await event_provider.write_events(events)

        assert result == 2
        call_args = mock_conn.executemany.call_args
        rows = call_args[0][1]
        # First event should have "info" severity
        assert rows[0][4] == "info"  # severity at index 4
        # Second event should have "error" severity
        assert rows[1][4] == "error"

    async def test_query_events_builds_filter_clause(self, event_provider, mock_connection_manager):
        """Test that query_events builds correct WHERE clause."""
        mock_connection_manager.fetch.return_value = []

        await event_provider.query_events(
            event_type="indexing.complete",
            since=datetime(2024, 1, 1),
            limit=50,
        )

        call_args = mock_connection_manager.fetch.call_args
        sql = call_args[0][0]
        assert "event_type = " in sql
        assert "created_at > " in sql
        assert "ORDER BY created_at DESC" in sql
        assert "LIMIT" in sql

    async def test_get_operation_status_aggregates_correctly(self, event_provider, mock_connection_manager):
        """Test that get_operation_status uses aggregation."""
        mock_connection_manager.fetchrow.return_value = make_record(
            event_count=10,
            error_count=2,
            start_time=datetime(2024, 1, 1, 10, 0, 0),
            end_time=datetime(2024, 1, 1, 10, 5, 0),
            latest_type="indexing.complete",
            latest_severity="info",
        )

        result = await event_provider.get_operation_status("op-123")

        assert result["event_count"] == 10
        assert result["error_count"] == 2
        assert result["duration"] == 300.0  # 5 minutes
        call_args = mock_connection_manager.fetchrow.call_args
        sql = call_args[0][0]
        assert "COUNT(*)" in sql
        assert "FILTER" in sql

    async def test_delete_before_enforces_retention(self, event_provider, mock_connection_manager):
        """Test that delete_before deletes old events."""
        mock_connection_manager.execute.return_value = "DELETE 100"
        cutoff = datetime(2024, 1, 1)

        result = await event_provider.delete_before(cutoff)

        assert result == 100
        call_args = mock_connection_manager.execute.call_args
        sql = call_args[0][0]
        assert "DELETE FROM" in sql
        assert "created_at < " in sql

    async def test_run_maintenance_vacuums_table(self, event_provider, mock_connection_manager):
        """Test that run_maintenance performs VACUUM ANALYZE."""
        mock_connection_manager.fetchval.return_value = 50  # event count

        # Mock acquire context manager
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_connection_manager.acquire.return_value.__aenter__.return_value = mock_conn

        result = await event_provider.run_maintenance()

        assert result["status"] == "completed"
        assert result["events_count"] == 50
        call_args = mock_conn.execute.call_args
        assert "VACUUM ANALYZE" in call_args[0][0]


# =============================================================================
# PostgresFileTrackerProvider Tests
# =============================================================================


class TestPostgresFileTrackerProviderUnit:
    """Unit tests for PostgresFileTrackerProvider with mocked asyncpg."""

    @pytest.fixture
    def file_tracker(self, mock_connection_manager):
        """Create a file tracker with mocked connection."""
        from agent_vault.storage.providers.postgresql import PostgresFileTrackerProvider

        provider = PostgresFileTrackerProvider(
            connection_manager=mock_connection_manager,
            project_id="test-project",
        )
        provider._initialized = True
        return provider

    async def test_get_hash_queries_by_project_and_path(self, file_tracker, mock_connection_manager):
        """Test that get_hash queries with correct parameters."""
        mock_connection_manager.fetchval.return_value = "abc123def456"

        result = await file_tracker.get_hash("/test/file.py")

        assert result == "abc123def456"
        call_args = mock_connection_manager.fetchval.call_args
        sql = call_args[0][0]
        assert "content_hash" in sql
        assert "project_id = " in sql
        assert "file_path = " in sql

    async def test_update_hash_uses_upsert(self, file_tracker, mock_connection_manager):
        """Test that update_hash uses INSERT ON CONFLICT."""
        result = await file_tracker.update_hash("/test/file.py", "newhash123")

        assert result == "newhash123"
        call_args = mock_connection_manager.execute.call_args
        sql = call_args[0][0]
        assert "INSERT INTO" in sql
        assert "ON CONFLICT" in sql
        assert "DO UPDATE" in sql

    async def test_has_changed_with_no_stored_hash(self, file_tracker, mock_connection_manager):
        """Test that has_changed returns True when file not tracked."""
        mock_connection_manager.fetchval.return_value = None  # No stored hash

        # Mock _compute_file_hash to avoid file system
        with patch.object(file_tracker, '_compute_file_hash', return_value="currenthash"):
            result = await file_tracker.has_changed("/test/file.py")

        assert result is True  # Not tracked = changed

    async def test_has_changed_with_same_hash(self, file_tracker, mock_connection_manager):
        """Test that has_changed returns False when hash matches."""
        mock_connection_manager.fetchval.return_value = "samehash123"

        with patch.object(file_tracker, '_compute_file_hash', return_value="samehash123"):
            result = await file_tracker.has_changed("/test/file.py")

        assert result is False

    async def test_has_changed_with_different_hash(self, file_tracker, mock_connection_manager):
        """Test that has_changed returns True when hash differs."""
        mock_connection_manager.fetchval.return_value = "oldhash123"

        with patch.object(file_tracker, '_compute_file_hash', return_value="newhash456"):
            result = await file_tracker.has_changed("/test/file.py")

        assert result is True

    async def test_remove_file_returns_true_on_delete(self, file_tracker, mock_connection_manager):
        """Test that remove_file returns True when row deleted."""
        mock_connection_manager.execute.return_value = "DELETE 1"

        result = await file_tracker.remove_file("/test/file.py")

        assert result is True

    async def test_remove_file_returns_false_when_not_found(self, file_tracker, mock_connection_manager):
        """Test that remove_file returns False when no row deleted."""
        mock_connection_manager.execute.return_value = "DELETE 0"

        result = await file_tracker.remove_file("/test/file.py")

        assert result is False

    async def test_list_tracked_files_returns_tuples(self, file_tracker, mock_connection_manager):
        """Test that list_tracked_files returns (path, hash) tuples."""
        mock_connection_manager.fetch.return_value = [
            make_record(file_path="/test/a.py", content_hash="hash1"),
            make_record(file_path="/test/b.py", content_hash="hash2"),
        ]

        result = await file_tracker.list_tracked_files()

        assert len(result) == 2
        assert result[0] == ("/test/a.py", "hash1")
        assert result[1] == ("/test/b.py", "hash2")

    async def test_clear_deletes_project_files(self, file_tracker, mock_connection_manager):
        """Test that clear deletes only current project's files."""
        mock_connection_manager.execute.return_value = "DELETE 10"

        await file_tracker.clear()

        call_args = mock_connection_manager.execute.call_args
        sql = call_args[0][0]
        assert "DELETE FROM" in sql
        assert "project_id = " in sql


# =============================================================================
# PostgresConnectionManager Tests
# =============================================================================


class TestPostgresConnectionManagerUnit:
    """Unit tests for PostgresConnectionManager."""

    def test_from_config_creates_manager(self):
        """Test that from_config creates a properly configured manager."""
        from agent_vault.storage.providers.postgresql import PostgresConnectionManager

        config = {
            "connection_string": "postgresql://user:pass@localhost/db",
            "pool_size": 20,
            "min_pool_size": 5,
        }

        manager = PostgresConnectionManager.from_config(config, table_prefix="test_")

        assert manager.connection_string == config["connection_string"]
        assert manager.pool_size == 20
        assert manager.min_pool_size == 5
        assert manager.table_prefix == "test_"

    def test_from_config_default_pool_size_is_backend_aware(self):
        """AlloyDB small instances share ``max_connections=25`` across the
        project. The generic pool_size=10 default is too high — concurrent
        indexing exhausts the pool. AlloyDB defaults to 5; other pg-family
        variants stay at 10 where instances typically have 100+ connections.
        Explicit ``pool_size`` overrides always win.
        """
        from agent_vault.storage.providers.postgresql import PostgresConnectionManager

        base_config = {"connection_string": "postgresql://user:pass@localhost/db"}

        # AlloyDB gets the lower default
        alloydb_mgr = PostgresConnectionManager.from_config(
            {**base_config, "type": "alloydb"}
        )
        assert alloydb_mgr.pool_size == 5

        # Other variants keep the 10 default
        for variant in ("postgresql", "cloudsql", "rds", "azure"):
            mgr = PostgresConnectionManager.from_config(
                {**base_config, "type": variant}
            )
            assert mgr.pool_size == 10, (
                f"Expected pool_size=10 for {variant}, got {mgr.pool_size}"
            )

        # Explicit override wins even for AlloyDB
        alloydb_override = PostgresConnectionManager.from_config(
            {**base_config, "type": "alloydb", "pool_size": 20}
        )
        assert alloydb_override.pool_size == 20

    def test_from_config_command_timeout_by_backend_type(self):
        """Cloud-hosted + server-side-embedding backends get a long
        ``command_timeout`` because their bulk embedding paths are slow
        (AlloyDB ``ai.initialize_embeddings``, RDS Bedrock fallback, Azure
        per-row generation, CloudSQL shares the AlloyDB-adjacent tooling).
        Self-hosted postgresql stays on the short default since there's no
        slow helper in the default install. Explicit ``command_timeout``
        overrides always win.
        """
        from agent_vault.storage.providers.postgresql import PostgresConnectionManager

        base_config = {"connection_string": "postgresql://user:pass@localhost/db"}

        # All four cloud/server-side variants share the 900s default
        for variant in ("alloydb", "cloudsql", "rds", "azure"):
            mgr = PostgresConnectionManager.from_config(
                {**base_config, "type": variant}
            )
            assert mgr.command_timeout == 900.0, (
                f"Expected command_timeout=900.0 for {variant}, "
                f"got {mgr.command_timeout}"
            )

        # Self-hosted postgresql stays on 60s
        pg_mgr = PostgresConnectionManager.from_config(
            {**base_config, "type": "postgresql"}
        )
        assert pg_mgr.command_timeout == 60.0

        # Explicit override wins even on a cloud variant
        override_mgr = PostgresConnectionManager.from_config(
            {**base_config, "type": "alloydb", "command_timeout": 30.0}
        )
        assert override_mgr.command_timeout == 30.0

    def test_get_table_name_applies_role_prefix(self):
        """Test that get_table_name applies correct role prefixes."""
        from agent_vault.storage.providers.postgresql import PostgresConnectionManager

        manager = PostgresConnectionManager(
            connection_string="postgresql://localhost/db",
            table_prefix="agv_",
        )

        assert manager.get_table_name("chunks", "vector") == "agv_v_chunks"
        assert manager.get_table_name("entities", "graph") == "agv_g_entities"
        assert manager.get_table_name("events", "events") == "agv_e_events"
        assert manager.get_table_name("file_hashes", "file_tracker") == "agv_f_file_hashes"

    def test_repr_masks_password(self):
        """Test that __repr__ masks the password in connection string."""
        from agent_vault.storage.providers.postgresql import PostgresConnectionManager

        manager = PostgresConnectionManager(
            connection_string="postgresql://user:secretpassword@localhost/db",
        )

        repr_str = repr(manager)

        assert "secretpassword" not in repr_str
        assert "****" in repr_str
        assert "user:" in repr_str

    def test_raises_on_empty_connection_string(self):
        """Test that empty connection string raises ValueError."""
        from agent_vault.storage.providers.postgresql import PostgresConnectionManager

        with pytest.raises(ValueError, match="connection_string is required"):
            PostgresConnectionManager(connection_string="")

    async def test_initialize_raises_without_asyncpg(self):
        """Test that initialize raises ImportError if asyncpg not available."""
        from agent_vault.storage.providers.postgresql import PostgresConnectionManager

        manager = PostgresConnectionManager(
            connection_string="postgresql://localhost/db",
        )

        # Mock asyncpg import to fail
        with patch.dict('sys.modules', {'asyncpg': None}):
            with patch('builtins.__import__', side_effect=ImportError("No module named 'asyncpg'")):
                with pytest.raises(ImportError, match="asyncpg is required"):
                    await manager.initialize()


class TestAlloyDBConnectionManagerUnit:
    """Unit tests for AlloyDBConnectionManager defaults.

    The PostgreSQL provider's ``from_config`` dispatches ``type="alloydb"``
    to ``AlloyDBConnectionManager`` rather than ``PostgresConnectionManager``
    (see ``postgresql/vector.py:from_config`` and ``postgresql/graph.py:from_config``),
    so the AlloyDB-specific default tuning must live on ``AlloyDBConnectionManager``
    to actually take effect on the primary vector/graph paths. These tests pin
    those defaults at the real dispatch site.
    """

    @staticmethod
    def _alloydb_config(**overrides):
        """Minimal valid AlloyDB config dict."""
        base = {
            "type": "alloydb",
            "project": "test-project",
            "region": "us-central1",
            "cluster": "test-cluster",
            "instance": "test-instance",
            "database": "test-db",
            "user": "test-user",
        }
        base.update(overrides)
        return base

    def test_from_config_default_pool_size_is_5(self):
        """AlloyDB small instances share ``max_connections=25`` project-wide;
        ``BackendConfig``'s generic ``pool_size=10`` default eats ~40% of that
        budget. ``AlloyDBConnectionManager.from_config`` must inject 5 as the
        AlloyDB-appropriate default when the config dict omits ``pool_size``.
        """
        from agent_vault.storage.providers.alloydb import AlloyDBConnectionManager

        mgr = AlloyDBConnectionManager.from_config(self._alloydb_config())

        assert mgr.pool_size == 5, (
            f"Expected pool_size=5 default for AlloyDB, got {mgr.pool_size}. "
            "Generic BackendConfig default is 10, which exhausts max_connections=25 "
            "on AlloyDB small instances under concurrent indexing."
        )

    def test_from_config_respects_explicit_pool_size(self):
        """Operators on larger AlloyDB tiers must be able to override the 5 default."""
        from agent_vault.storage.providers.alloydb import AlloyDBConnectionManager

        mgr = AlloyDBConnectionManager.from_config(
            self._alloydb_config(pool_size=20)
        )

        assert mgr.pool_size == 20

    def test_command_timeout_is_900s(self):
        """``ai.initialize_embeddings`` on large tables can run past 5 min;
        the previous 300s hardcode surfaced as command timeouts on realistic
        first-run bulk loads. 900s (15 min) matches the
        ``PostgresConnectionManager`` default for the other cloud variants.
        """
        from agent_vault.storage.providers.alloydb import AlloyDBConnectionManager

        mgr = AlloyDBConnectionManager.from_config(self._alloydb_config())

        assert mgr.command_timeout == 900.0, (
            f"Expected command_timeout=900.0 for AlloyDB, got {mgr.command_timeout}. "
            "Historical hardcode was 300s which timed out on ai.initialize_embeddings."
        )

    def test_from_config_respects_explicit_command_timeout(self):
        """Operator overrides of ``command_timeout`` must flow through —
        the value used to be hardcoded in ``__init__``, which silently
        dropped any user-supplied value on the primary vector/graph paths
        (where AlloyDB routes through ``AlloyDBConnectionManager``,
        bypassing ``PostgresConnectionManager.from_config`` entirely).
        """
        from agent_vault.storage.providers.alloydb import AlloyDBConnectionManager

        mgr = AlloyDBConnectionManager.from_config(
            self._alloydb_config(command_timeout=30.0)
        )

        assert mgr.command_timeout == 30.0

    def test_event_provider_exercises_postgres_connection_manager_alloydb_backstop(self):
        """``PostgresEventProvider.from_config`` routes ``type=alloydb`` through
        ``PostgresConnectionManager.from_config`` (not ``AlloyDBConnectionManager``
        — unlike vector/graph), so the events role is the one that genuinely
        exercises the PG-side AlloyDB backstop defaults.

        This pins that the backstop is live on a real production role, not
        justified only by reasoning: previously the AlloyDB-branch defaults
        in ``PostgresConnectionManager.from_config`` had no test that walked
        through a provider whose ``from_config`` path actually used them.
        """
        from agent_vault.storage.providers.postgresql import PostgresEventProvider

        provider = PostgresEventProvider.from_config(
            {
                "type": "alloydb",
                "connection_string": "postgresql://user:pass@localhost/db",
            },
            project_id="test-project",
        )

        cm = provider._connection_manager
        assert cm.pool_size == 5, (
            "Expected PG-side AlloyDB backstop pool_size=5 to apply to the "
            f"events role via PostgresConnectionManager, got {cm.pool_size}"
        )
        assert cm.command_timeout == 900.0, (
            "Expected PG-side AlloyDB backstop command_timeout=900.0 to apply "
            f"to the events role, got {cm.command_timeout}"
        )
