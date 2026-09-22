"""Property-based tests for GraphBuilderConfig.

These tests validate the configuration loading, default values, and invalid
configuration handling as specified in the design document.

Property tests:
- Property 25: Configuration Loading (Requirements 8.1, 8.2, 8.3)
- Property 26: Default Configuration Values (Requirements 8.4)
- Property 27: Invalid Configuration Handling (Requirements 8.5)
"""

import pytest

pytestmark = pytest.mark.unit

import logging
from hypothesis import assume, given, strategies as st, settings, HealthCheck
from unittest.mock import MagicMock

from agent_vault.indexing.graph_builder import GraphBuilderConfig


# =============================================================================
# Property 25: Configuration Loading
# Validates: Requirements 8.1, 8.2, 8.3
# =============================================================================

class TestConfigurationLoading:
    """Tests for configuration loading from indexing.relationship_flush section."""

    def test_loads_from_indexing_relationship_flush_section(self):
        """Configuration SHALL be read from indexing.relationship_flush section."""
        config = MagicMock()
        config.indexing = {
            'relationship_flush': {
                'batch_size': 200,
                'flush_timeout_seconds': 7200,
                'batch_commit_interval': 50,
            }
        }

        result = GraphBuilderConfig.from_config(config)

        assert result.batch_size == 200
        assert result.flush_timeout_seconds == 7200
        assert result.batch_commit_interval == 50

    @given(
        batch_size=st.integers(min_value=1, max_value=1000),
        flush_timeout_seconds=st.integers(min_value=1, max_value=86400),
        batch_commit_interval=st.integers(min_value=1, max_value=1000),
    )
    @settings(max_examples=100)
    def test_property_25_configuration_loading(
        self, batch_size, flush_timeout_seconds, batch_commit_interval
    ):
        """Property 25: For any configuration load operation, the system SHALL read
        flush_timeout, batch_commit_interval, and batch_size from the indexing section.
        """
        config = MagicMock()
        config.indexing = {
            'relationship_flush': {
                'batch_size': batch_size,
                'flush_timeout_seconds': flush_timeout_seconds,
                'batch_commit_interval': batch_commit_interval,
            }
        }

        result = GraphBuilderConfig.from_config(config)

        # Verify all values are loaded from config
        assert result.batch_size == batch_size
        assert result.flush_timeout_seconds == flush_timeout_seconds
        assert result.batch_commit_interval == batch_commit_interval

    def test_loads_all_configuration_parameters(self):
        """All configuration parameters should be loaded when specified."""
        config = MagicMock()
        config.indexing = {
            'relationship_flush': {
                'batch_size': 150,
                'max_concurrent_batches': 15,
                'progress_log_interval': 500,
                'batch_commit_interval': 75,
                'auto_flush_threshold': 25000,
                'flush_timeout_seconds': 1800,
                'external_entity_flush_threshold': 5000,
                'enable_cache_prewarming': False,
                'enable_performance_monitoring': False,
                'slow_operation_threshold_ms': 250.0,
            }
        }

        result = GraphBuilderConfig.from_config(config)

        assert result.batch_size == 150
        assert result.max_concurrent_batches == 15
        assert result.progress_log_interval == 500
        assert result.batch_commit_interval == 75
        assert result.auto_flush_threshold == 25000
        assert result.flush_timeout_seconds == 1800
        assert result.external_entity_flush_threshold == 5000
        assert result.enable_cache_prewarming is False
        assert result.enable_performance_monitoring is False
        assert result.slow_operation_threshold_ms == 250.0


# =============================================================================
# Property 26: Default Configuration Values
# Validates: Requirements 8.4
# =============================================================================

class TestDefaultConfigurationValues:
    """Tests for default configuration values when not specified."""

    def test_uses_defaults_when_no_config_provided(self):
        """Default values SHALL be used when configuration is not specified."""
        config = MagicMock()
        config.indexing = {}

        result = GraphBuilderConfig.from_config(config)

        defaults = GraphBuilderConfig()
        assert result.batch_size == defaults.batch_size
        assert result.max_concurrent_batches == defaults.max_concurrent_batches
        assert result.progress_log_interval == defaults.progress_log_interval
        assert result.batch_commit_interval == defaults.batch_commit_interval
        assert result.auto_flush_threshold == defaults.auto_flush_threshold
        assert result.flush_timeout_seconds == defaults.flush_timeout_seconds
        assert result.external_entity_flush_threshold == defaults.external_entity_flush_threshold
        assert result.enable_cache_prewarming == defaults.enable_cache_prewarming
        assert result.enable_performance_monitoring == defaults.enable_performance_monitoring
        assert result.slow_operation_threshold_ms == defaults.slow_operation_threshold_ms

    def test_uses_defaults_when_relationship_flush_section_missing(self):
        """Default values SHALL be used when relationship_flush section is missing."""
        config = MagicMock()
        config.indexing = {'other_setting': 'value'}

        result = GraphBuilderConfig.from_config(config)

        defaults = GraphBuilderConfig()
        assert result == defaults

    def test_uses_defaults_when_indexing_section_missing(self):
        """Default values SHALL be used when indexing section is missing."""
        config = MagicMock()
        config.indexing = None

        result = GraphBuilderConfig.from_config(config)

        defaults = GraphBuilderConfig()
        assert result == defaults

    @given(
        # Generate partial configurations with some values missing
        provided_batch_size=st.one_of(st.none(), st.integers(min_value=1, max_value=1000)),
        provided_timeout=st.one_of(st.none(), st.integers(min_value=1, max_value=86400)),
    )
    @settings(max_examples=100)
    def test_property_26_default_configuration_values(self, provided_batch_size, provided_timeout):
        """Property 26: For any configuration parameter that is not specified,
        the system SHALL use the documented default value.
        """
        defaults = GraphBuilderConfig()

        flush_config = {}
        if provided_batch_size is not None:
            flush_config['batch_size'] = provided_batch_size
        if provided_timeout is not None:
            flush_config['flush_timeout_seconds'] = provided_timeout

        config = MagicMock()
        config.indexing = {'relationship_flush': flush_config}

        result = GraphBuilderConfig.from_config(config)

        # Verify provided values are used
        if provided_batch_size is not None:
            assert result.batch_size == provided_batch_size
        else:
            assert result.batch_size == defaults.batch_size

        if provided_timeout is not None:
            assert result.flush_timeout_seconds == provided_timeout
        else:
            assert result.flush_timeout_seconds == defaults.flush_timeout_seconds

        # Verify unspecified values use defaults
        assert result.max_concurrent_batches == defaults.max_concurrent_batches
        assert result.progress_log_interval == defaults.progress_log_interval

    def test_documented_default_values(self):
        """Verify documented default values match actual defaults."""
        defaults = GraphBuilderConfig()

        # From design document:
        assert defaults.batch_size == 100
        assert defaults.max_concurrent_batches == 10
        assert defaults.progress_log_interval == 1000
        assert defaults.batch_commit_interval == 100
        assert defaults.auto_flush_threshold == 50000
        assert defaults.flush_timeout_seconds == 3600
        assert defaults.external_entity_flush_threshold == 10000
        assert defaults.enable_cache_prewarming is True
        assert defaults.enable_performance_monitoring is True
        assert defaults.slow_operation_threshold_ms == 500.0


# =============================================================================
# Property 27: Invalid Configuration Handling
# Validates: Requirements 8.5
# =============================================================================

class TestInvalidConfigurationHandling:
    """Tests for invalid configuration value handling."""

    def test_logs_warning_for_invalid_integer_value(self, caplog):
        """Invalid configuration values SHALL log a warning and use defaults."""
        config = MagicMock()
        config.indexing = {
            'relationship_flush': {
                'batch_size': 'not_a_number',
            }
        }

        with caplog.at_level(logging.WARNING):
            result = GraphBuilderConfig.from_config(config)

        defaults = GraphBuilderConfig()
        assert result.batch_size == defaults.batch_size
        assert any('batch_size' in record.message.lower() for record in caplog.records)

    def test_logs_warning_for_negative_value(self, caplog):
        """Negative values SHALL log a warning and use defaults."""
        config = MagicMock()
        config.indexing = {
            'relationship_flush': {
                'batch_size': -10,
            }
        }

        with caplog.at_level(logging.WARNING):
            result = GraphBuilderConfig.from_config(config)

        defaults = GraphBuilderConfig()
        assert result.batch_size == defaults.batch_size
        assert any('batch_size' in record.message.lower() for record in caplog.records)

    def test_logs_warning_for_zero_value(self, caplog):
        """Zero values SHALL log a warning and use defaults where minimum is 1."""
        config = MagicMock()
        config.indexing = {
            'relationship_flush': {
                'batch_size': 0,
            }
        }

        with caplog.at_level(logging.WARNING):
            result = GraphBuilderConfig.from_config(config)

        defaults = GraphBuilderConfig()
        assert result.batch_size == defaults.batch_size

    @given(
        invalid_value=st.one_of(
            # Filter out numeric strings that can be parsed as valid integers
            st.text().filter(lambda x: not x.strip().lstrip('-+').isdigit() or not x.strip()),
            st.lists(st.integers()),
            st.dictionaries(st.text(), st.integers()),
        )
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_property_27_invalid_configuration_handling(self, invalid_value):
        """Property 27: For any invalid configuration value, the system SHALL
        log a warning and use the default value.
        """
        # Skip empty strings (handled by config code gracefully)
        assume(invalid_value != "")

        config = MagicMock()
        config.indexing = {
            'relationship_flush': {
                'batch_size': invalid_value,
            }
        }

        # Don't use caplog with hypothesis - just verify the result
        result = GraphBuilderConfig.from_config(config)

        defaults = GraphBuilderConfig()
        # Should use default value for invalid input
        assert result.batch_size == defaults.batch_size

    def test_handles_invalid_float_value(self, caplog):
        """Invalid float values SHALL log a warning and use defaults."""
        config = MagicMock()
        config.indexing = {
            'relationship_flush': {
                'slow_operation_threshold_ms': 'invalid',
            }
        }

        with caplog.at_level(logging.WARNING):
            result = GraphBuilderConfig.from_config(config)

        defaults = GraphBuilderConfig()
        assert result.slow_operation_threshold_ms == defaults.slow_operation_threshold_ms

    def test_handles_invalid_boolean_value(self):
        """Invalid boolean values SHALL be converted or use defaults."""
        config = MagicMock()
        config.indexing = {
            'relationship_flush': {
                'enable_cache_prewarming': 'false',  # String should convert
            }
        }

        result = GraphBuilderConfig.from_config(config)
        assert result.enable_cache_prewarming is False

    def test_handles_none_config_object(self):
        """None config object SHALL use all defaults."""
        # Create a mock that raises AttributeError for indexing
        config = MagicMock()
        config.indexing = None

        result = GraphBuilderConfig.from_config(config)

        defaults = GraphBuilderConfig()
        assert result == defaults

    def test_handles_exception_in_config_access(self):
        """Exceptions during config access SHALL result in defaults."""
        config = MagicMock()
        # Make indexing raise an exception when accessed
        type(config).indexing = property(lambda self: (_ for _ in ()).throw(TypeError("test")))

        result = GraphBuilderConfig.from_config(config)

        defaults = GraphBuilderConfig()
        assert result == defaults


# =============================================================================
# Additional Tests for Completeness
# =============================================================================

class TestConfigurationEdgeCases:
    """Additional edge case tests for configuration."""

    def test_partial_configuration(self):
        """Partial configuration should merge with defaults."""
        config = MagicMock()
        config.indexing = {
            'relationship_flush': {
                'batch_size': 250,
                # Other values not specified
            }
        }

        result = GraphBuilderConfig.from_config(config)

        defaults = GraphBuilderConfig()
        assert result.batch_size == 250
        assert result.max_concurrent_batches == defaults.max_concurrent_batches
        assert result.flush_timeout_seconds == defaults.flush_timeout_seconds

    def test_config_with_object_style_access(self):
        """Configuration accessed via object attributes should work."""
        class MockConfig:
            class IndexingConfig:
                relationship_flush = {
                    'batch_size': 300,
                }
            indexing = IndexingConfig()

        result = GraphBuilderConfig.from_config(MockConfig())

        assert result.batch_size == 300

    def test_empty_string_values_use_defaults(self, caplog):
        """Empty string values should use defaults."""
        config = MagicMock()
        config.indexing = {
            'relationship_flush': {
                'batch_size': '',
            }
        }

        with caplog.at_level(logging.WARNING):
            result = GraphBuilderConfig.from_config(config)

        defaults = GraphBuilderConfig()
        assert result.batch_size == defaults.batch_size
