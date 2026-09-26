"""Unit tests for LanceDBSchemaManager."""

import asyncio
from collections import defaultdict
from unittest.mock import MagicMock

import pytest

from agentic_inquiry.database.schema_manager import LanceDBSchemaManager

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_db():
    """Create a mock LanceDB connection."""
    db = MagicMock()
    db.open_table = MagicMock()
    return db


@pytest.fixture
def mock_table():
    """Create a mock LanceDB table."""
    table = MagicMock()
    table.name = "test_table"
    table.count_rows = MagicMock(return_value=0)
    table.list_indices = MagicMock(return_value=[])
    table.create_index = MagicMock()
    table.create_fts_index = MagicMock()
    return table


@pytest.fixture
def mock_tables():
    """Create a mock tables dictionary."""
    return {}


@pytest.fixture
def table_configs():
    """Create test table configurations."""
    return {
        "test_table": {
            "vector_columns": ["embedding"],
            "fts_columns": ["content"],
        },
        "two_fts_table": {
            "vector_columns": ["embedding"],
            "fts_columns": ["title", "content"],
        },
    }


@pytest.fixture
def mock_ensure_db(mock_db):
    """Create a mock ensure_db function."""

    def _ensure_db():
        return mock_db

    return _ensure_db


@pytest.fixture
async def mock_run_sync():
    """Create a mock run_sync function."""

    async def _run_sync(fn, *args):
        return fn(*args) if args else fn()

    return _run_sync


@pytest.fixture
def schema_manager(mock_ensure_db, mock_run_sync, mock_tables, table_configs):
    """Create a schema manager instance."""
    return LanceDBSchemaManager(
        ensure_db_fn=mock_ensure_db,
        run_sync_fn=mock_run_sync,
        tables=mock_tables,
        table_configs=table_configs,
        table_lock=defaultdict(asyncio.Lock).__getitem__,
    )


class TestTableCreation:
    """Test table creation and initialization."""

    async def test_create_tables_and_indexes_opens_existing(
        self, schema_manager, mock_db, mock_table, mock_tables
    ):
        """Test opening existing tables."""
        # Setup mock to return existing table
        mock_db.open_table = MagicMock(return_value=mock_table)

        # Execute
        await schema_manager.create_tables_and_indexes()

        # Verify table was opened
        assert mock_db.open_table.call_count >= 1
        assert "test_table" in mock_tables or "two_fts_table" in mock_tables

    async def test_create_tables_and_indexes_handles_missing(
        self, schema_manager, mock_db, mock_tables
    ):
        """Test handling of missing tables."""
        # Setup mock to raise exception (table doesn't exist)
        mock_db.open_table = MagicMock(side_effect=Exception("Table not found"))

        # Execute - should not raise
        await schema_manager.create_tables_and_indexes()

        # Verify tables dict is still empty (tables weren't created)
        assert len(mock_tables) == 0


class TestIndexCreation:
    """Test index creation logic."""

    def test_ensure_indexes_creates_vector_index(self, schema_manager, mock_table):
        """Test creating vector index."""
        # Execute
        schema_manager._ensure_indexes_sync(
            table_name="test_table",
            table=mock_table,
            existing_indices=[],
        )

        # Verify vector index was created
        mock_table.create_index.assert_called_once()
        call_args = mock_table.create_index.call_args
        assert call_args.kwargs["metric"] == "cosine"
        assert call_args.kwargs["vector_column_name"] == "embedding"

    def test_ensure_indexes_honours_similarity_metric(
        self, mock_ensure_db, mock_run_sync, mock_tables, table_configs, mock_table
    ):
        """Non-default similarity_metric is passed through to create_index."""
        manager = LanceDBSchemaManager(
            ensure_db_fn=mock_ensure_db,
            run_sync_fn=mock_run_sync,
            tables=mock_tables,
            table_configs=table_configs,
            table_lock=defaultdict(asyncio.Lock).__getitem__,
            similarity_metric="l2",
        )

        manager._ensure_indexes_sync(
            table_name="test_table",
            table=mock_table,
            existing_indices=[],
        )

        mock_table.create_index.assert_called_once()
        assert mock_table.create_index.call_args.kwargs["metric"] == "l2"

    def test_ensure_indexes_rejects_unknown_similarity_metric(
        self, mock_ensure_db, mock_run_sync, mock_tables, table_configs
    ):
        """Unknown similarity_metric names fail fast at construction."""
        with pytest.raises(ValueError, match="unsupported similarity_metric"):
            LanceDBSchemaManager(
                ensure_db_fn=mock_ensure_db,
                run_sync_fn=mock_run_sync,
                tables=mock_tables,
                table_configs=table_configs,
                table_lock=defaultdict(asyncio.Lock).__getitem__,
                similarity_metric="hamming",
            )

    def test_ensure_indexes_creates_fts_index(self, schema_manager, mock_table):
        """Test creating FTS index."""
        # Execute
        schema_manager._ensure_indexes_sync(
            table_name="test_table",
            table=mock_table,
            existing_indices=[],
        )

        # Verify FTS index was created
        mock_table.create_fts_index.assert_called_once_with("content", replace=False)

    def test_ensure_indexes_creates_one_native_fts_index_per_column(
        self, schema_manager, mock_table
    ):
        """Each configured FTS column gets its own native single-column index."""
        schema_manager._ensure_indexes_sync(
            table_name="two_fts_table",
            table=mock_table,
            existing_indices=[],
        )

        calls = mock_table.create_fts_index.call_args_list
        assert [call_obj.args[0] for call_obj in calls] == ["title", "content"]
        for call_obj in calls:
            assert isinstance(call_obj.args[0], str)
            assert call_obj.kwargs.get("use_tantivy") is not True

    def test_ensure_indexes_skips_existing(self, schema_manager, mock_table):
        """Test skipping existing indexes."""
        # Setup existing indices
        existing = [
            MagicMock(columns=["embedding"]),
            MagicMock(columns=["content"]),
        ]

        # Execute
        schema_manager._ensure_indexes_sync(
            table_name="test_table",
            table=mock_table,
            existing_indices=existing,
        )

        # Verify no indexes were created
        mock_table.create_index.assert_not_called()
        mock_table.create_fts_index.assert_not_called()

    def test_ensure_indexes_handles_errors(self, schema_manager, mock_table, caplog):
        """Test handling index creation errors."""
        # Setup mock to raise exception
        mock_table.create_index = MagicMock(side_effect=Exception("Index error"))

        # Execute - should not raise
        schema_manager._ensure_indexes_sync(
            table_name="test_table",
            table=mock_table,
            existing_indices=[],
        )

        # Verify error was logged
        assert "Failed to create vector index" in caplog.text


class TestDatabaseValidation:
    """Test database integrity validation."""

    async def test_validate_database_integrity_all_valid(
        self, schema_manager, mock_table, mock_tables
    ):
        """Test validation with all tables valid."""
        # Setup
        mock_tables["test_table"] = mock_table
        mock_tables["two_fts_table"] = mock_table

        # Execute
        result = await schema_manager.validate_database_integrity()

        # Verify
        assert result["valid"] is True
        assert "test_table" in result["tables"]
        assert result["tables"]["test_table"]["exists"] is True
        assert result["tables"]["test_table"]["accessible"] is True

    async def test_validate_database_integrity_missing_table(
        self, schema_manager, mock_tables
    ):
        """Test validation with missing table."""
        # Execute (tables dict is empty)
        result = await schema_manager.validate_database_integrity()

        # Verify
        assert result["valid"] is False
        assert "test_table" in result["tables"]
        assert result["tables"]["test_table"]["exists"] is False
        errors = result["tables"]["test_table"]["errors"]
        assert len(errors) > 0
        # Verify actual error content describes the missing table
        assert any(
            "not found" in str(err).lower() or "missing" in str(err).lower()
            for err in errors
        )

    async def test_validate_database_integrity_inaccessible_table(
        self, schema_manager, mock_table, mock_tables
    ):
        """Test validation with inaccessible table."""
        # Setup table that raises error on access
        mock_table.count_rows = MagicMock(side_effect=Exception("Access denied"))
        mock_tables["test_table"] = mock_table

        # Execute
        result = await schema_manager.validate_database_integrity()

        # Verify
        assert result["valid"] is False
        assert result["tables"]["test_table"]["exists"] is True
        assert result["tables"]["test_table"]["accessible"] is False

    async def test_validate_database_integrity_checks_indices(
        self, schema_manager, mock_table, mock_tables
    ):
        """Test validation checks for indices."""
        # Setup table with indices
        mock_table.list_indices = MagicMock(
            return_value=[
                MagicMock(columns=["embedding"]),
                MagicMock(columns=["content"]),
            ]
        )
        mock_tables["test_table"] = mock_table

        # Execute
        result = await schema_manager.validate_database_integrity()

        # Verify
        assert result["tables"]["test_table"]["has_indices"] is True
        assert result["tables"]["test_table"]["index_count"] == 2


class TestSchemaManagerDelegation:
    """Test that LanceDBManager properly delegates to SchemaManager."""

    async def test_manager_delegates_create_tables(
        self, schema_manager, mock_db, mock_table
    ):
        """Test that create_tables_and_indexes is properly delegated."""
        # Setup
        mock_db.open_table = MagicMock(return_value=mock_table)

        # Execute
        await schema_manager.create_tables_and_indexes()

        # Verify delegation occurred
        assert mock_db.open_table.called

    async def test_manager_delegates_validation(
        self, schema_manager, mock_table, mock_tables
    ):
        """Test that validate_database_integrity is properly delegated."""
        # Setup
        mock_tables["test_table"] = mock_table

        # Execute
        result = await schema_manager.validate_database_integrity()

        # Verify delegation occurred and returned proper structure
        assert "valid" in result
        assert "tables" in result
        assert isinstance(result["tables"], dict)
