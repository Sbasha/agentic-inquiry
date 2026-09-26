"""Unit tests for LanceDBQueryBuilder."""

import pytest
from unittest.mock import MagicMock

pytestmark = pytest.mark.unit

from agentic_inquiry.database.query_builder import LanceDBQueryBuilder


@pytest.fixture
def mock_table():
    """Create a mock LanceDB table."""
    table = MagicMock()
    table.search = MagicMock()
    return table


@pytest.fixture
async def mock_get_table(mock_table):
    """Create a mock get_table function."""

    async def _get_table(table_name: str):
        return mock_table

    return _get_table


@pytest.fixture
async def mock_run_sync():
    """Create a mock run_sync function."""

    async def _run_sync(fn, *args):
        return fn(*args) if args else fn()

    return _run_sync


@pytest.fixture
async def query_builder(mock_get_table, mock_run_sync):
    """Create a query builder instance."""
    return LanceDBQueryBuilder(
        get_table_fn=mock_get_table,
        run_sync_fn=mock_run_sync,
        project_id="test-project",
    )


class TestQueryConstruction:
    """Test query construction methods."""

    async def test_vector_search_basic(self, query_builder, mock_table):
        """Test basic vector search query construction."""
        # Setup mock - query_builder uses refine_factor() for accurate distance calculations
        query_mock = MagicMock()
        query_mock.where = MagicMock(return_value=query_mock)
        query_mock.refine_factor = MagicMock(return_value=query_mock)
        query_mock.limit = MagicMock(return_value=query_mock)
        query_mock.to_list = MagicMock(return_value=[{"id": "1", "content": "test"}])
        mock_table.search = MagicMock(return_value=query_mock)

        # Execute
        results = await query_builder.vector_search(
            table_name="test_table",
            query_vector=[0.1, 0.2, 0.3],
            vector_column_name="embedding",
            limit=10,
        )

        # Verify
        assert len(results) == 1
        assert results[0]["id"] == "1"
        mock_table.search.assert_called_once()

    async def test_vector_search_with_filters(self, query_builder, mock_table):
        """Test vector search with filters."""
        # Setup mock
        query_mock = MagicMock()
        query_mock.where = MagicMock(return_value=query_mock)
        query_mock.limit = MagicMock(return_value=query_mock)
        query_mock.to_list = MagicMock(return_value=[])
        mock_table.search = MagicMock(return_value=query_mock)

        # Execute
        await query_builder.vector_search(
            table_name="test_table",
            query_vector=[0.1, 0.2, 0.3],
            vector_column_name="embedding",
            limit=10,
            filters={"type": "document"},
        )

        # Verify where was called with filter expression
        query_mock.where.assert_called_once()
        call_args = query_mock.where.call_args[0][0]
        assert "type = 'document'" in call_args
        assert "project_id = 'test-project'" in call_args

    async def test_fts_search_basic(self, query_builder, mock_table):
        """Test basic FTS search query construction."""
        # Setup mock
        query_mock = MagicMock()
        query_mock.where = MagicMock(return_value=query_mock)
        query_mock.limit = MagicMock(return_value=query_mock)
        query_mock.to_list = MagicMock(return_value=[{"id": "1", "content": "test"}])
        mock_table.search = MagicMock(return_value=query_mock)

        # Execute
        results = await query_builder.fts_search(
            table_name="test_table",
            query="search term",
            limit=10,
        )

        # Verify
        assert len(results) == 1
        mock_table.search.assert_called_once_with("search term", query_type="fts")

    async def test_hybrid_search(self, query_builder, mock_table):
        """Test hybrid search query construction."""
        # Setup mock - hybrid search uses .text().vector() chaining
        query_mock = MagicMock()
        query_mock.text = MagicMock(return_value=query_mock)
        query_mock.vector = MagicMock(return_value=query_mock)
        query_mock.where = MagicMock(return_value=query_mock)
        query_mock.limit = MagicMock(return_value=query_mock)
        query_mock.to_list = MagicMock(return_value=[])
        mock_table.search = MagicMock(return_value=query_mock)

        # Execute
        await query_builder.hybrid_search(
            table_name="test_table",
            query="search term",
            query_vector=[0.1, 0.2, 0.3],
            vector_column_name="embedding",
            limit=10,
        )

        # Verify - hybrid search now uses search(query_type="hybrid").text(query).vector(vector)
        mock_table.search.assert_called_once_with(query_type="hybrid")
        query_mock.text.assert_called_once_with("search term")
        query_mock.vector.assert_called_once()


class TestFilterConstruction:
    """Test filter expression construction using FilterBuilder."""

    def test_filter_builder_string(self):
        """Test filter with string value."""
        from agentic_inquiry.database.filters import FilterBuilder

        builder = FilterBuilder()
        builder.add_field_filter("name", "test")
        expr = builder.build()
        assert expr == "name = 'test'"

    def test_filter_builder_int(self):
        """Test filter with integer value."""
        from agentic_inquiry.database.filters import FilterBuilder

        builder = FilterBuilder()
        builder.add_field_filter("count", 42)
        expr = builder.build()
        assert expr == "count = 42"

    def test_filter_builder_bool(self):
        """Test filter with boolean value."""
        from agentic_inquiry.database.filters import FilterBuilder

        builder = FilterBuilder()
        builder.add_field_filter("active", True)
        expr = builder.build()
        assert expr == "active = true"

    def test_filter_builder_null(self):
        """Test filter with null value."""
        from agentic_inquiry.database.filters import FilterBuilder

        builder = FilterBuilder()
        builder.add_field_filter("value", None)
        expr = builder.build()
        assert expr == "value IS NULL"

    def test_filter_builder_list(self):
        """Test filter with list value."""
        from agentic_inquiry.database.filters import FilterBuilder

        builder = FilterBuilder()
        builder.add_field_filter("type", ["a", "b", "c"])
        expr = builder.build()
        assert expr == "type IN ('a', 'b', 'c')"

    def test_filter_in_operator_tuple_format(self, query_builder):
        """Test IN operator using tuple format: ('IN', [values])."""
        filters = {"type": ("IN", ["code", "doc", "test"])}
        expr = query_builder._filters_to_expression(filters)

        # Verify IN clause is generated correctly
        assert "type IN ('code', 'doc', 'test')" in expr

    def test_filter_in_operator_with_integers(self, query_builder):
        """Test IN operator with integer values."""
        filters = {"priority": ("IN", [1, 2, 3])}
        expr = query_builder._filters_to_expression(filters)

        assert "priority IN (1, 2, 3)" in expr

    def test_filter_in_operator_empty_list(self, query_builder):
        """Test IN operator with empty list returns FALSE."""
        filters = {"status": ("IN", [])}
        expr = query_builder._filters_to_expression(filters)

        # Empty IN list should translate to FALSE
        assert "FALSE" in expr

    def test_filters_to_expression_multiple(self, query_builder):
        """Test combining multiple filters."""
        filters = {
            "name": "test",
            "count": 42,
            "active": True,
        }
        expr = query_builder._filters_to_expression(filters)

        # Check all filters are present
        assert "name = 'test'" in expr
        assert "count = 42" in expr
        assert "active = true" in expr
        assert " AND " in expr

    def test_filters_to_expression_empty(self, query_builder):
        """Test empty filters."""
        expr = query_builder._filters_to_expression({})
        assert expr == ""

    def test_filter_builder_escapes_quotes(self):
        """Test that single quotes are escaped."""
        from agentic_inquiry.database.filters import FilterBuilder

        builder = FilterBuilder()
        builder.add_field_filter("name", "test'value")
        expr = builder.build()
        assert expr == "name = 'test''value'"


class TestProjectFiltering:
    """Test project filtering logic."""

    async def test_add_project_filter_current(self, query_builder):
        """Test adding current project filter."""
        filters = query_builder._add_project_filter({}, "current")
        assert filters == {"project_id": "test-project"}

    async def test_add_project_filter_specific(self, query_builder):
        """Test adding specific project filter."""
        filters = query_builder._add_project_filter({}, "other-project")
        assert filters == {"project_id": "other-project"}

    async def test_add_project_filter_none(self, query_builder):
        """Test no project filtering."""
        filters = query_builder._add_project_filter({"type": "doc"}, None)
        assert filters == {"type": "doc"}
        assert "project_id" not in filters

    async def test_add_project_filter_preserves_existing(self, query_builder):
        """Test that existing filters are preserved."""
        filters = query_builder._add_project_filter(
            {"type": "doc", "count": 5}, "current"
        )
        assert filters == {"type": "doc", "count": 5, "project_id": "test-project"}


class TestCrossProjectQueries:
    """Test cross-project query methods."""

    async def test_query_across_projects(self, query_builder, mock_table):
        """Test querying across all projects."""
        # Setup mock
        query_mock = MagicMock()
        query_mock.where = MagicMock(return_value=query_mock)
        query_mock.limit = MagicMock(return_value=query_mock)
        query_mock.to_list = MagicMock(return_value=[])
        mock_table.search = MagicMock(return_value=query_mock)

        # Execute
        await query_builder.query_across_projects(
            table_name="test_table",
            filters={"type": "document"},
            limit=100,
        )

        # Verify no project filter was added
        call_args = query_mock.where.call_args[0][0]
        assert "project_id" not in call_args
        assert "type = 'document'" in call_args

    async def test_vector_search_across_projects(self, query_builder, mock_table):
        """Test vector search across all projects."""
        # Setup mock
        query_mock = MagicMock()
        query_mock.where = MagicMock(return_value=query_mock)
        query_mock.limit = MagicMock(return_value=query_mock)
        query_mock.to_list = MagicMock(return_value=[])
        mock_table.search = MagicMock(return_value=query_mock)

        # Execute
        await query_builder.vector_search_across_projects(
            table_name="test_table",
            query_vector=[0.1, 0.2, 0.3],
            vector_column_name="embedding",
            limit=10,
        )

        # Verify search was called without project filter
        mock_table.search.assert_called_once()
        # If where was called, verify no project_id filter
        if query_mock.where.called:
            call_args = query_mock.where.call_args[0][0]
            assert "project_id" not in call_args
