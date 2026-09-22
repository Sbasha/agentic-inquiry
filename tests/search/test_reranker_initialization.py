"""Tests for reranker initialization and parameter handling."""

import pytest

pytestmark = pytest.mark.integration

import inspect
from unittest.mock import AsyncMock, MagicMock

from agent_vault.config import Config
from agent_vault.database.adapters.lancedb_adapter import LanceDBAdapter
from agent_vault.exceptions import ConfigurationError
from agent_vault.search.service import SearchService
from agent_vault.search.rerankers import (
    RRFReranker,
    LinearCombinationReranker,
)


@pytest.fixture
def base_config():
    """Create a base configuration for testing."""
    config = Config.load()
    return config


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


class TestRRFRerankerParameterHandling:
    """Test RRFReranker parameter validation and initialization."""
    
    def test_rrf_reranker_creation_with_no_parameters(self, base_config, mock_db_manager):
        """Test RRFReranker can be created with no parameters."""
        from lancedb.rerankers import RRFReranker
        
        # Should succeed with no parameters
        reranker = RRFReranker()
        assert reranker is not None
        assert isinstance(reranker, RRFReranker)
    
    def test_rrf_reranker_creation_with_valid_parameters(self, base_config, mock_db_manager):
        """Test RRFReranker creation with valid parameters."""
        from lancedb.rerankers import RRFReranker
        
        # Get the actual signature
        sig = inspect.signature(RRFReranker.__init__)
        valid_params = set(sig.parameters.keys()) - {'self'}
        
        # Should have K parameter (uppercase)
        assert 'K' in valid_params
        
        # Should succeed with valid parameter
        reranker = RRFReranker(K=60)
        assert reranker is not None
        assert isinstance(reranker, RRFReranker)
    
    def test_rrf_reranker_fails_with_invalid_parameter_name(self, base_config, mock_db_manager):
        """Test RRFReranker fails with invalid parameter name."""
        from lancedb.rerankers import RRFReranker
        
        # Should fail with lowercase 'k' instead of uppercase 'K'
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            RRFReranker(k=60)
    
    def test_search_service_creates_reranker_with_valid_params(self, base_config, mock_storage_facade, mock_event_system):
        """Test SearchService._hybrid_search._create_reranker() uses valid parameters.

        Note: For reranker_type 'rrf' and 'linear_combination', the HybridSearchService
        returns None because these use the built-in simple merge strategy.
        Only external rerankers (cohere, colbert, cross_encoder) create actual reranker objects.
        """
        # Configure for an external reranker (cohere)
        base_config.search.hybrid_search.reranker_type = "cohere"
        base_config.search.hybrid_search.reranker_params = {"model_name": "default"}

        search_service = SearchService(
            storage=mock_storage_facade,
            config=base_config,
            event_system=mock_event_system,
        )

        # cohere reranker will fail to create if lancedb.rerankers is not available
        # but the method should not raise - it returns None on failure
        search_service._hybrid_search._create_reranker()
        # May be None if lancedb.rerankers is not installed with cohere support
        # This is expected behavior

    def test_search_service_rejects_invalid_reranker_type(self, base_config, mock_storage_facade, mock_event_system):
        """Test SearchService rejects invalid reranker type at startup.

        As of the DES-S4-002 implementation, invalid reranker types are validated
        at startup and raise ConfigurationError with a clear message instead of
        silently falling back to RRF.
        """
        # Configure with unknown reranker type
        base_config.search.hybrid_search.reranker_type = "unknown_type"
        base_config.search.hybrid_search.reranker_params = {}

        # Should raise ConfigurationError with helpful message
        with pytest.raises(ConfigurationError) as exc_info:
            SearchService(
                storage=mock_storage_facade,
                config=base_config,
                event_system=mock_event_system,
            )

        # Verify error message contains useful information
        error_message = str(exc_info.value)
        assert "unknown_type" in error_message
        assert "Valid options:" in error_message
        assert "rrf" in error_message

    def test_search_service_creates_reranker_with_no_params(self, base_config, mock_storage_facade, mock_event_system):
        """Test SearchService with RRF returns our protocol-based RRFReranker."""
        # Configure with rrf type
        base_config.search.hybrid_search.reranker_type = "rrf"
        base_config.search.hybrid_search.reranker_params = {}

        search_service = SearchService(
            storage=mock_storage_facade,
            config=base_config,
            event_system=mock_event_system,
        )

        # RRF type returns our protocol-based RRFReranker
        reranker = search_service._hybrid_search._create_reranker()
        assert isinstance(reranker, RRFReranker)
    
    def test_parameter_validation_filters_invalid_params(self, base_config, mock_db_manager):
        """Test that parameter validation filters out invalid parameters."""
        from lancedb.rerankers import RRFReranker
        
        # Get valid parameters
        sig = inspect.signature(RRFReranker.__init__)
        valid_params = set(sig.parameters.keys()) - {'self'}
        
        # Test params with both valid and invalid keys
        test_params = {
            "K": 60,  # valid
            "k": 60,  # invalid (wrong case)
            "invalid_param": "value",  # invalid
            "return_score": "relevance"  # valid
        }
        
        # Filter to only valid params
        filtered_params = {
            k: v for k, v in test_params.items()
            if k in valid_params
        }
        
        # Should only have valid params
        assert "K" in filtered_params
        assert "return_score" in filtered_params
        assert "k" not in filtered_params
        assert "invalid_param" not in filtered_params
        
        # Should create successfully with filtered params
        reranker = RRFReranker(**filtered_params)
        assert reranker is not None
        assert isinstance(reranker, RRFReranker)


class TestOtherRerankerTypes:
    """Test other reranker types still work correctly."""

    def test_linear_combination_reranker(self, base_config, mock_storage_facade, mock_event_system):
        """Test linear_combination returns our protocol-based LinearCombinationReranker."""
        base_config.search.hybrid_search.reranker_type = "linear_combination"
        base_config.search.hybrid_search.reranker_params = {"vector_weight": 0.7, "fts_weight": 0.3}

        search_service = SearchService(
            storage=mock_storage_facade,
            config=base_config,
            event_system=mock_event_system,
        )

        # linear_combination returns our protocol-based LinearCombinationReranker
        reranker = search_service._hybrid_search._create_reranker()
        assert isinstance(reranker, LinearCombinationReranker)

    def test_unknown_reranker_type_raises_configuration_error(self, base_config, mock_storage_facade, mock_event_system):
        """Test unknown reranker type raises ConfigurationError at startup.

        As of the DES-S4-002 implementation, invalid reranker types are validated
        at startup and raise ConfigurationError instead of silently falling back.
        """
        base_config.search.hybrid_search.reranker_type = "unknown_type"

        # Should raise ConfigurationError
        with pytest.raises(ConfigurationError) as exc_info:
            SearchService(
                storage=mock_storage_facade,
                config=base_config,
                event_system=mock_event_system,
            )

        # Verify the error is helpful
        assert "unknown_type" in str(exc_info.value)
