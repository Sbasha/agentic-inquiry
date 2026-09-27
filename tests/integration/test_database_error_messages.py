"""Test database operation error messages (Example 9).

This module tests that database operation failures provide helpful error
messages with operation type and suggested remediation.

**Validates: Requirements 9.4**
"""

import pytest


import tempfile
from unittest.mock import patch, MagicMock
from agentic_inquiry.database.lancedb_manager import LanceDBManager
from agentic_inquiry.exceptions import StorageError
from agentic_inquiry.config import Config


class TestDatabaseErrorMessages:
    """Test database operation error messages provide helpful context."""

    @pytest.mark.asyncio
    async def test_database_error_includes_operation_type(self):
        """Test that database errors include operation type.

        **Example 9: Database operation error**
        **Validates: Requirements 9.4**

        Verifies that:
        - Error includes operation type (e.g., "add_rows")
        - Error includes table name
        - Error includes suggested remediation
        """
        # Create a temporary database
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config.load()
            config.storage.root = tmpdir

            db_manager = LanceDBManager.from_config(config)

            # Create a mock table object
            mock_table = MagicMock()
            mock_table.add.side_effect = Exception("Table not found")

            # Patch get_or_create_table to return our mock table
            with patch.object(
                db_manager, "_get_or_create_table", return_value=(mock_table, False)
            ):
                # Try to add rows which should fail
                with pytest.raises(StorageError) as exc_info:
                    await db_manager._add_rows(
                        "test_table", [{"id": "1", "data": "test"}]
                    )

                error = exc_info.value
                error_msg = str(error)

                # Verify error includes operation type
                assert "add_rows" in error_msg

                # Verify error includes table name
                assert "test_table" in error_msg

                # Verify error includes suggestion
                assert "Suggestion:" in error_msg or "suggestion" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_table_not_found_error_suggestion(self):
        """Test that table not found errors get appropriate suggestions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config.load()
            config.storage.root = tmpdir

            db_manager = LanceDBManager.from_config(config)

            mock_table = MagicMock()
            mock_table.add.side_effect = Exception("table not found")

            with patch.object(
                db_manager, "_get_or_create_table", return_value=(mock_table, False)
            ):
                with pytest.raises(StorageError) as exc_info:
                    await db_manager._add_rows("missing_table", [{"id": "1"}])

                error_msg = str(exc_info.value)

                # Verify suggestion mentions table creation
                assert "table" in error_msg.lower()
                assert any(
                    word in error_msg.lower() for word in ["recreat", "creat", "exist"]
                )

    @pytest.mark.asyncio
    async def test_schema_mismatch_error_suggestion(self):
        """Test that schema mismatch errors get appropriate suggestions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config.load()
            config.storage.root = tmpdir

            db_manager = LanceDBManager.from_config(config)

            mock_table = MagicMock()
            mock_table.add.side_effect = Exception("schema mismatch: column type error")

            with patch.object(
                db_manager, "_get_or_create_table", return_value=(mock_table, False)
            ):
                with pytest.raises(StorageError) as exc_info:
                    await db_manager._add_rows("test_table", [{"id": "1"}])

                error_msg = str(exc_info.value)

                # Verify suggestion mentions schema validation
                assert "schema" in error_msg.lower()
                assert any(
                    word in error_msg.lower() for word in ["field", "type", "match"]
                )

    @pytest.mark.asyncio
    async def test_permission_error_suggestion(self):
        """Test that permission errors get appropriate suggestions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config.load()
            config.storage.root = tmpdir

            db_manager = LanceDBManager.from_config(config)

            mock_table = MagicMock()
            mock_table.add.side_effect = Exception("permission denied")

            with patch.object(
                db_manager, "_get_or_create_table", return_value=(mock_table, False)
            ):
                with pytest.raises(StorageError) as exc_info:
                    await db_manager._add_rows("test_table", [{"id": "1"}])

                error_msg = str(exc_info.value)

                # Verify suggestion mentions permissions
                assert "permission" in error_msg.lower()
                assert any(
                    word in error_msg.lower()
                    for word in ["access", "write", "directory"]
                )

    @pytest.mark.asyncio
    async def test_disk_space_error_suggestion(self):
        """Test that disk space errors get appropriate suggestions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config.load()
            config.storage.root = tmpdir

            db_manager = LanceDBManager.from_config(config)

            mock_table = MagicMock()
            mock_table.add.side_effect = Exception("no space left on disk")

            with patch.object(
                db_manager, "_get_or_create_table", return_value=(mock_table, False)
            ):
                with pytest.raises(StorageError) as exc_info:
                    await db_manager._add_rows("test_table", [{"id": "1"}])

                error_msg = str(exc_info.value)

                # Verify suggestion mentions disk space
                assert "disk" in error_msg.lower() or "space" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_generic_database_error_suggestion(self):
        """Test that generic database errors get appropriate suggestions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config.load()
            config.storage.root = tmpdir

            db_manager = LanceDBManager.from_config(config)

            mock_table = MagicMock()
            mock_table.add.side_effect = Exception("unknown database error")

            with patch.object(
                db_manager, "_get_or_create_table", return_value=(mock_table, False)
            ):
                with pytest.raises(StorageError) as exc_info:
                    await db_manager._add_rows("test_table", [{"id": "1"}])

                error_msg = str(exc_info.value)

                # Verify suggestion provides general guidance
                assert "Suggestion:" in error_msg or "suggestion" in error_msg.lower()
                assert any(
                    word in error_msg.lower()
                    for word in ["database", "connection", "storage"]
                )
