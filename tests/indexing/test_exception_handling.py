"""Tests for exception handling in indexing components.

This module tests that critical system signals (KeyboardInterrupt, SystemExit)
are not caught by exception handlers, while recoverable exceptions are properly
caught and logged.
"""

import pytest

pytestmark = pytest.mark.unit

import logging
from unittest.mock import AsyncMock, MagicMock, patch

from agentic_inquiry.indexing.graph_builder import GraphBuilder
from agentic_inquiry.parsers.models import ParserRelationship


class TestGraphBuilderExceptionHandling:
    """Test exception handling in GraphBuilder."""

    @pytest.fixture
    def mock_db_manager(self):
        """Create a mock database manager."""
        mock_db_manager = MagicMock()
        mock_db_manager.get_entity_by_id = AsyncMock(return_value=None)
        return mock_db_manager

    @pytest.fixture
    def mock_symbol_registry(self):
        """Create a mock symbol registry."""
        return MagicMock()

    @pytest.fixture
    def mock_relationship_resolver(self):
        """Create a mock relationship resolver."""
        resolver = MagicMock()
        resolver.resolve_import = AsyncMock(return_value=None)
        return resolver

    @pytest.fixture
    def mock_embedding_service(self):
        """Create a mock embedding service."""
        return MagicMock()

    @pytest.fixture
    def graph_builder(
        self,
        mock_db_manager,
        mock_symbol_registry,
        mock_relationship_resolver,
        mock_embedding_service,
    ):
        """Create a GraphBuilder instance with mocked dependencies."""
        builder = GraphBuilder(
            db_manager=mock_db_manager,
            symbol_registry=mock_symbol_registry,
            relationship_resolver=mock_relationship_resolver,
            embedding_service=mock_embedding_service,
            project_id="test_project",
            project_hash="test_hash",
            project_root="/tmp/test_project",
        )
        return builder

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_not_caught(
        self, graph_builder, mock_relationship_resolver
    ):
        """Test that KeyboardInterrupt propagates correctly and is not caught."""
        # Create a test relationship
        relationship = ParserRelationship(
            source_type="module",
            source_name="test_source",
            target_type="function",
            target_name="test_target",
            type="calls",
        )

        # Mock Path.suffix to raise KeyboardInterrupt
        with patch(
            "pathlib.Path.suffix",
            new_callable=lambda: property(
                lambda self: (_ for _ in ()).throw(KeyboardInterrupt())
            ),
        ):
            # KeyboardInterrupt should propagate, not be caught
            with pytest.raises(KeyboardInterrupt):
                await graph_builder._resolve_import(
                    relationship=relationship,
                    source_file_path="test.py",
                    import_path=None,
                )

    @pytest.mark.asyncio
    async def test_system_exit_not_caught(
        self, graph_builder, mock_relationship_resolver
    ):
        """Test that SystemExit propagates correctly and is not caught."""
        # Create a test relationship
        relationship = ParserRelationship(
            source_type="module",
            source_name="test_source",
            target_type="function",
            target_name="test_target",
            type="calls",
        )

        # Mock Path.suffix to raise SystemExit
        with patch(
            "pathlib.Path.suffix",
            new_callable=lambda: property(
                lambda self: (_ for _ in ()).throw(SystemExit(1))
            ),
        ):
            # SystemExit should propagate, not be caught
            with pytest.raises(SystemExit):
                await graph_builder._resolve_import(
                    relationship=relationship,
                    source_file_path="test.py",
                    import_path=None,
                )

    @pytest.mark.asyncio
    async def test_exception_caught_and_logged(
        self, graph_builder, mock_relationship_resolver, caplog
    ):
        """Test that Exception is caught and logged with traceback."""
        # Create a test relationship
        relationship = ParserRelationship(
            source_type="module",
            source_name="test_source",
            target_type="function",
            target_name="test_target",
            type="calls",
        )

        # Mock Path to raise TypeError (a recoverable exception)
        with patch("pathlib.Path") as mock_path:
            mock_path.side_effect = TypeError("Invalid path type")

            # Capture logs at WARNING level
            with caplog.at_level(logging.WARNING):
                # Should not raise, should continue with empty source_language
                result = await graph_builder._resolve_import(
                    relationship=relationship,
                    source_file_path=None,  # This will cause TypeError
                    import_path=None,
                )

                # Verify the method completed (returned result from resolver)
                assert result is None  # Mock returns None

                # Verify exception was logged
                assert any(
                    "Failed to determine source language" in record.message
                    for record in caplog.records
                )

    @pytest.mark.asyncio
    async def test_exception_logged_with_exc_info(
        self, graph_builder, mock_relationship_resolver, caplog
    ):
        """Test that exceptions are logged with full traceback (exc_info=True)."""
        # Create a test relationship
        relationship = ParserRelationship(
            source_type="module",
            source_name="test_source",
            target_type="function",
            target_name="test_target",
            type="calls",
        )

        # Mock Path to raise AttributeError
        with patch("pathlib.Path") as mock_path:
            mock_path.side_effect = AttributeError("Invalid attribute access")

            # Capture logs at WARNING level
            with caplog.at_level(logging.WARNING):
                # Should not raise
                await graph_builder._resolve_import(
                    relationship=relationship,
                    source_file_path="invalid",
                    import_path=None,
                )

                # Verify exception was logged with exc_info
                warning_records = [
                    record
                    for record in caplog.records
                    if "Failed to determine source language" in record.message
                ]
                assert len(warning_records) > 0

                # Check that exc_info was included (traceback available)
                assert any(record.exc_info is not None for record in warning_records)

    @pytest.mark.asyncio
    async def test_valid_path_no_exception(
        self, graph_builder, mock_relationship_resolver
    ):
        """Test that valid paths work correctly without exceptions."""
        # Create a test relationship
        relationship = ParserRelationship(
            source_type="module",
            source_name="test_source",
            target_type="function",
            target_name="test_target",
            type="calls",
        )

        # Should work without raising any exceptions
        await graph_builder._resolve_import(
            relationship=relationship, source_file_path="test.py", import_path=None
        )

        # Verify the resolver was called with correct language
        mock_relationship_resolver.resolve_import.assert_called_once()
        call_kwargs = mock_relationship_resolver.resolve_import.call_args.kwargs
        assert call_kwargs["source_language"] == "python"
