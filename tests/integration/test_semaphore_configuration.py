"""Unit tests for semaphore configuration.

Tests the processing_semaphore_limit configuration field in IndexingConfig,
including default values, validation, and integration with IndexingPipeline.
"""

import pytest

from unittest.mock import AsyncMock, MagicMock

from agentic_inquiry.config import Config, IndexingConfig
from agentic_inquiry.exceptions import ConfigurationError
from agentic_inquiry.indexing.pipeline import IndexingPipeline


def _create_mock_event_system():
    """Create a mock event system for tests."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


class TestSemaphoreConfiguration:
    """Test suite for semaphore limit configuration."""

    def test_default_value_is_20(self, mock_config):
        """Test that the default semaphore limit is 20.

        Raised from 10 to 20 after PR #134 batched per-file embedding;
        with the embedding executor no longer starved by serial per-chunk
        calls, file-level concurrency can actually use the extra budget.
        """
        # Requirements: 7.2
        config = Config.load()
        assert config.indexing.processing_semaphore_limit == 20

    def test_validation_rejects_values_less_than_1(self):
        """Test that validation rejects values < 1."""
        # Requirements: 7.2, 7.3
        with pytest.raises(ConfigurationError) as exc_info:
            IndexingConfig(processing_semaphore_limit=0)

        error_msg = str(exc_info.value)
        assert "processing_semaphore_limit must be between 1 and 100" in error_msg
        assert "got 0" in error_msg

    def test_validation_rejects_negative_values(self):
        """Test that validation rejects negative values."""
        # Requirements: 7.2, 7.3
        with pytest.raises(ConfigurationError) as exc_info:
            IndexingConfig(processing_semaphore_limit=-5)

        error_msg = str(exc_info.value)
        assert "processing_semaphore_limit must be between 1 and 100" in error_msg
        assert "got -5" in error_msg

    def test_validation_rejects_values_greater_than_100(self):
        """Test that validation rejects values > 100."""
        # Requirements: 7.2, 7.3
        with pytest.raises(ConfigurationError) as exc_info:
            IndexingConfig(processing_semaphore_limit=101)

        error_msg = str(exc_info.value)
        assert "processing_semaphore_limit must be between 1 and 100" in error_msg
        assert "got 101" in error_msg

    def test_validation_accepts_boundary_value_1(self):
        """Test that validation accepts the minimum boundary value of 1."""
        # Requirements: 7.2, 7.3
        config = IndexingConfig(processing_semaphore_limit=1)
        assert config.processing_semaphore_limit == 1

    def test_validation_accepts_boundary_value_100(self):
        """Test that validation accepts the maximum boundary value of 100."""
        # Requirements: 7.2, 7.3
        config = IndexingConfig(processing_semaphore_limit=100)
        assert config.processing_semaphore_limit == 100

    def test_validation_accepts_valid_middle_values(self):
        """Test that validation accepts valid values in the middle of the range."""
        # Requirements: 7.2, 7.3
        for value in [1, 10, 25, 50, 75, 100]:
            config = IndexingConfig(processing_semaphore_limit=value)
            assert config.processing_semaphore_limit == value

    def test_error_message_includes_recommendations(self):
        """Test that error messages include helpful recommendations."""
        # Requirements: 7.2, 7.3
        with pytest.raises(ConfigurationError) as exc_info:
            IndexingConfig(processing_semaphore_limit=200)

        error_msg = str(exc_info.value)
        assert "Lower values reduce concurrency" in error_msg
        assert "higher values increase throughput" in error_msg
        assert "Recommended:" in error_msg

    async def test_indexing_pipeline_respects_configured_limit(
        self, mock_db_manager, mock_config
    ):
        """Test that IndexingPipeline respects the configured semaphore limit."""
        # Requirements: 7.2, 7.3
        # Set a custom limit
        mock_config.indexing.processing_semaphore_limit = 5

        # Create pipeline
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=mock_config,
            project_id="test_project",
            event_system=_create_mock_event_system(),
        )

        # Verify the semaphore was created with the correct limit
        assert pipeline._processing_semaphore._value == 5

    async def test_indexing_pipeline_uses_default_when_not_specified(
        self, mock_db_manager, mock_config
    ):
        """Test that IndexingPipeline uses default limit when not explicitly set."""
        # Requirements: 7.2
        # Don't modify the config, use default
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=mock_config,
            project_id="test_project",
            event_system=_create_mock_event_system(),
        )

        # Verify the semaphore was created with the default limit
        # (raised from 10 → 20 with batched embedding).
        assert pipeline._processing_semaphore._value == 20

    async def test_max_concurrent_parameter_deprecated(
        self, mock_db_manager, mock_config
    ):
        """Test that max_concurrent parameter shows deprecation warning."""
        # Verify backward compatibility with deprecation warning
        with pytest.warns(
            DeprecationWarning, match="max_concurrent parameter is deprecated"
        ):
            pipeline = IndexingPipeline(
                db_manager=mock_db_manager,
                config=mock_config,
                project_id="test_project",
                event_system=_create_mock_event_system(),
                max_concurrent=15,
            )

        # Verify the deprecated parameter still works
        assert pipeline._processing_semaphore._value == 15

    async def test_config_takes_precedence_over_deprecated_parameter(
        self, mock_db_manager, mock_config
    ):
        """Test that when max_concurrent is not provided, config value is used."""
        # Set config value
        mock_config.indexing.processing_semaphore_limit = 20

        # Create pipeline without max_concurrent
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=mock_config,
            project_id="test_project",
            event_system=_create_mock_event_system(),
        )

        # Verify config value is used
        assert pipeline._processing_semaphore._value == 20
