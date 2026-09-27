"""Tests for S5-002: Verify exceptions are logged instead of silently suppressed.

These tests ensure that previously silent exception handlers now log appropriately.
"""

import pytest

pytestmark = pytest.mark.unit

import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from agentic_inquiry.mcp.services.temporal_analyzer import TemporalAnalyzer


class TestTemporalAnalyzerExceptionLogging:
    """Test that TemporalAnalyzer logs exceptions instead of silently passing."""

    @pytest.fixture
    def mock_db_manager(self):
        """Create a mock database manager."""
        db_manager = AsyncMock()
        return db_manager

    @pytest.fixture
    def mock_storage_facade(self, mock_db_manager):
        """Create mock StorageFacade that wraps the mock_db_manager."""
        mock_storage = MagicMock()
        mock_storage.get_db_manager = MagicMock(return_value=mock_db_manager)
        # TemporalAnalyzer calls these methods directly on db_manager (StorageFacade)
        mock_storage.advanced_filter = AsyncMock(return_value=[])
        mock_storage.query_entities = AsyncMock(return_value=[])
        return mock_storage

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = MagicMock()
        config.mcp.query.batch_limit = 10000
        return config

    @pytest.fixture
    def analyzer(self, mock_storage_facade, mock_config):
        """Create a TemporalAnalyzer instance."""
        return TemporalAnalyzer(mock_storage_facade, mock_config)

    @pytest.mark.asyncio
    async def test_get_recent_chunks_logs_invalid_timestamps(
        self, analyzer, mock_storage_facade, caplog
    ):
        """Verify that invalid timestamps in chunks are logged, not silently skipped."""
        # Setup: Return chunks with invalid timestamps
        mock_storage_facade.advanced_filter.return_value = [
            {"file_path": "test.py", "last_modified": "invalid-timestamp"},
            {"file_path": "test2.py", "last_modified": "2024-01-01T00:00:00Z"},
        ]

        cutoff_date = datetime.now() - timedelta(days=7)

        with caplog.at_level(logging.DEBUG):
            await analyzer._get_recent_chunks("test-project", cutoff_date)

        # Should log the invalid timestamp error
        assert any(
            "Skipping chunk with invalid timestamp" in record.message
            for record in caplog.records
        ), "Expected debug log for invalid timestamp"

        # Should still return valid chunks
        # (depending on the cutoff, valid chunk may or may not be included)

    @pytest.mark.asyncio
    async def test_identify_new_files_logs_invalid_created_at(
        self, analyzer, mock_storage_facade, caplog
    ):
        """Verify that invalid created_at timestamps are logged."""
        mock_storage_facade.advanced_filter.return_value = [
            {"file_path": "test.py", "created_at": "not-a-date"},
        ]

        cutoff_date = datetime.now() - timedelta(days=7)

        with caplog.at_level(logging.DEBUG):
            await analyzer._identify_new_files("test-project", cutoff_date)

        # Should log the parsing failure
        assert any(
            "invalid created_at timestamp" in record.message
            for record in caplog.records
        ), "Expected debug log for invalid created_at"

    @pytest.mark.asyncio
    async def test_identify_stale_areas_logs_invalid_last_change(
        self, analyzer, mock_storage_facade, caplog
    ):
        """Verify that invalid last_change timestamps are logged."""
        mock_storage_facade.advanced_filter.return_value = [
            {"file_path": "/path/test.py", "last_modified": "broken-date"},
        ]

        cutoff_date = datetime.now() - timedelta(days=7)

        with caplog.at_level(logging.DEBUG):
            await analyzer._identify_stale_areas("test-project", cutoff_date)

        # Should log the staleness calculation failure
        assert any(
            "invalid last_change timestamp" in record.message
            for record in caplog.records
        ), "Expected debug log for invalid last_change"


class TestSuggestionsExceptionLogging:
    """Test that suggestion generators log exceptions instead of silently passing."""

    @pytest.fixture
    def mock_search_service(self):
        """Create a mock search service."""
        service = AsyncMock()
        return service

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = MagicMock()
        config.embeddings = MagicMock()
        config.embeddings.default_dimensions = 384
        return config

    @pytest.mark.asyncio
    async def test_spelling_suggestion_logs_search_failure(
        self, mock_search_service, mock_config, caplog
    ):
        """Verify that spelling suggestion search failures are logged."""
        from agentic_inquiry.mcp.utils.suggestions import _generate_spelling_suggestions

        # Make fts_search raise an exception
        mock_search_service.fts_search.side_effect = Exception("Search failed")

        with caplog.at_level(logging.DEBUG):
            result = await _generate_spelling_suggestions(
                query="tset",  # typo for "test"
                search_service=mock_search_service,
                project_id="test-project",
            )

        # Should log the search failure
        assert any(
            "Spelling suggestion search failed" in record.message
            for record in caplog.records
        ), "Expected debug log for spelling suggestion failure"

        # Should return empty list gracefully
        assert result == []

    @pytest.mark.asyncio
    async def test_threshold_suggestion_logs_search_failure(
        self, mock_search_service, mock_config, caplog
    ):
        """Verify that threshold suggestion search failures are logged."""
        from agentic_inquiry.mcp.utils.suggestions import (
            _generate_threshold_suggestions,
        )

        # Make fts_search raise an exception
        mock_search_service.fts_search.side_effect = Exception("Search unavailable")

        with caplog.at_level(logging.DEBUG):
            await _generate_threshold_suggestions(
                query="multiple word query",
                search_service=mock_search_service,
                project_id="test-project",
                config=mock_config,
            )

        # Should log the search failure
        assert any(
            "Threshold suggestion search failed" in record.message
            for record in caplog.records
        ), "Expected debug log for threshold suggestion failure"


class TestDirectAccessExceptionLogging:
    """Test that direct access entity lookups log exceptions."""

    @pytest.mark.asyncio
    async def test_entity_lookup_logs_db_failure(self, caplog):
        """Verify that entity lookup failures are logged, not silently passed."""
        from agentic_inquiry.mcp.tools.direct_access import graph_traverse

        # Create mock services
        mock_config = MagicMock()
        mock_config.search.graph_search.timeouts.graph_traverse_ms = 5000

        mock_services = {
            "session_manager": AsyncMock(),
            "storage": AsyncMock(),
            "event_system": AsyncMock(),
            "config": mock_config,
        }
        mock_services["session_manager"].validate_session.return_value = True
        mock_services["session_manager"].get_session.return_value = MagicMock(
            project_id="test-project"
        )

        # Make db lookups fail
        mock_services["storage"].advanced_filter.side_effect = Exception(
            "DB connection lost"
        )

        with caplog.at_level(logging.DEBUG):
            result = await graph_traverse(
                services=mock_services,
                session_id="test-session",
                start_id="nonexistent-entity",
            )

        # Should log the lookup failures
        debug_messages = [
            r.message for r in caplog.records if r.levelno == logging.DEBUG
        ]
        assert any(
            "Entity lookup" in msg and "failed" in msg for msg in debug_messages
        ), f"Expected debug log for entity lookup failure, got: {debug_messages}"

        # Should return error response (entity not found) rather than crashing
        assert result["status"] == "failed"
        assert "not found" in result["error"]
