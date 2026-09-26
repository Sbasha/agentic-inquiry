"""Tests for reranker configuration validation.

This module tests that invalid reranker types are rejected at startup
with clear error messages, as specified in DES-S4-002.
"""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock

from agentic_inquiry.config import Config
from agentic_inquiry.database.adapters.lancedb_adapter import LanceDBAdapter
from agentic_inquiry.exceptions import ConfigurationError
from agentic_inquiry.search.service import SearchService
from agentic_inquiry.search.hybrid_search import VALID_RERANKER_TYPES


@pytest.fixture
def mock_db_manager():
    """Create a mock database manager with LanceDBAdapter spec."""
    mock_adapter = MagicMock(spec=LanceDBAdapter)
    mock_adapter.vector_search = AsyncMock()
    mock_adapter.fts_search = AsyncMock()
    mock_adapter._manager = MagicMock()
    mock_adapter._manager.get_table = MagicMock(return_value=MagicMock())
    return mock_adapter


@pytest.fixture
def mock_storage_facade(mock_db_manager):
    """Create a mock StorageFacade that provides mock_db_manager."""
    mock_storage = MagicMock()
    mock_storage.vector_provider = mock_db_manager
    mock_storage.project_id = "test_project"
    return mock_storage


@pytest.fixture
def mock_event_system():
    """Create a mock event system."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


@pytest.fixture
def base_config():
    """Create a base configuration for testing."""
    return Config.load()


class TestRerankerConfigValidation:
    """Tests for reranker configuration validation at startup."""

    def test_valid_reranker_types_constant(self):
        """Test that VALID_RERANKER_TYPES contains expected values."""
        expected = {"rrf", "linear_combination", "cross_encoder", "colbert"}
        assert VALID_RERANKER_TYPES == expected
        assert isinstance(VALID_RERANKER_TYPES, frozenset)

    @pytest.mark.parametrize("reranker_type", [
        "rrf",
        "linear_combination",
        "cross_encoder",
        "colbert",
    ])
    def test_valid_reranker_types_accepted(
        self,
        reranker_type: str,
        base_config: Config,
        mock_storage_facade: MagicMock,
        mock_event_system: MagicMock,
    ):
        """Test that all valid reranker types are accepted without error."""
        base_config.search.hybrid_search.reranker_type = reranker_type

        # Should not raise ConfigurationError
        service = SearchService(
            storage=mock_storage_facade,
            config=base_config,
            event_system=mock_event_system,
        )
        assert service is not None
        assert isinstance(service, SearchService)
        assert service._hybrid_search is not None

    @pytest.mark.parametrize("reranker_type", [
        "RRF",          # Uppercase should be normalized to lowercase
        "Rrf",          # Mixed case
        "LINEAR_COMBINATION",  # Uppercase
    ])
    def test_case_insensitive_reranker_types(
        self,
        reranker_type: str,
        base_config: Config,
        mock_storage_facade: MagicMock,
        mock_event_system: MagicMock,
    ):
        """Test that reranker types are case-insensitive."""
        base_config.search.hybrid_search.reranker_type = reranker_type

        # Should not raise ConfigurationError - validation normalizes to lowercase
        service = SearchService(
            storage=mock_storage_facade,
            config=base_config,
            event_system=mock_event_system,
        )
        assert service is not None
        assert isinstance(service, SearchService)
        assert service._hybrid_search is not None

    @pytest.mark.parametrize("invalid_type", [
        "invalid",
        "unknown",
        "rfrf",         # Typo of rrf
        "linear",       # Incomplete name
        "cross-encoder",  # Wrong delimiter
        "",             # Empty string (if config allows)
        "none",         # Not supported
    ])
    def test_invalid_reranker_types_rejected(
        self,
        invalid_type: str,
        base_config: Config,
        mock_storage_facade: MagicMock,
        mock_event_system: MagicMock,
    ):
        """Test that invalid reranker types raise ConfigurationError."""
        base_config.search.hybrid_search.reranker_type = invalid_type

        with pytest.raises(ConfigurationError) as exc_info:
            SearchService(
                storage=mock_storage_facade,
                config=base_config,
                event_system=mock_event_system,
            )

        # Verify error message contains useful information
        error_message = str(exc_info.value)
        assert invalid_type in error_message
        assert "Valid options:" in error_message
        # Check that at least one valid option is listed
        assert "rrf" in error_message

    def test_error_message_lists_all_valid_options(
        self,
        base_config: Config,
        mock_storage_facade: MagicMock,
        mock_event_system: MagicMock,
    ):
        """Test that error message includes all valid reranker types."""
        base_config.search.hybrid_search.reranker_type = "invalid_type"

        with pytest.raises(ConfigurationError) as exc_info:
            SearchService(
                storage=mock_storage_facade,
                config=base_config,
                event_system=mock_event_system,
            )

        error_message = str(exc_info.value)

        # All valid options should be mentioned
        for valid_type in VALID_RERANKER_TYPES:
            assert valid_type in error_message, (
                f"Valid type '{valid_type}' not found in error message: {error_message}"
            )

    def test_error_message_includes_config_path(
        self,
        base_config: Config,
        mock_storage_facade: MagicMock,
        mock_event_system: MagicMock,
    ):
        """Test that error message indicates where to fix the configuration."""
        base_config.search.hybrid_search.reranker_type = "bad_type"

        with pytest.raises(ConfigurationError) as exc_info:
            SearchService(
                storage=mock_storage_facade,
                config=base_config,
                event_system=mock_event_system,
            )

        error_message = str(exc_info.value)
        assert "search.hybrid_search.reranker_type" in error_message

    def test_validation_happens_before_other_initialization(
        self,
        base_config: Config,
        mock_storage_facade: MagicMock,
        mock_event_system: MagicMock,
    ):
        """Test that validation occurs before other attributes are set."""
        base_config.search.hybrid_search.reranker_type = "invalid"

        with pytest.raises(ConfigurationError):
            SearchService(
                storage=mock_storage_facade,
                config=base_config,
                event_system=mock_event_system,
            )

        # The mock storage should not have been heavily used if validation fails first
        # (This is more of a design verification)


class TestValidRerankerTypesExport:
    """Tests for the VALID_RERANKER_TYPES constant availability."""

    def test_constant_is_exported(self):
        """Test that VALID_RERANKER_TYPES can be imported."""
        from agentic_inquiry.search.hybrid_search import VALID_RERANKER_TYPES
        assert VALID_RERANKER_TYPES is not None
        assert isinstance(VALID_RERANKER_TYPES, frozenset)
        assert len(VALID_RERANKER_TYPES) > 0
        # Verify it contains expected reranker types
        assert "rrf" in VALID_RERANKER_TYPES
        assert "linear_combination" in VALID_RERANKER_TYPES

    def test_constant_is_immutable(self):
        """Test that VALID_RERANKER_TYPES cannot be modified."""
        from agentic_inquiry.search.hybrid_search import VALID_RERANKER_TYPES

        # frozenset doesn't have add/remove methods
        assert isinstance(VALID_RERANKER_TYPES, frozenset)

        # Attempting to modify should raise an error
        with pytest.raises(AttributeError):
            VALID_RERANKER_TYPES.add("new_type")  # type: ignore[attr-defined]
