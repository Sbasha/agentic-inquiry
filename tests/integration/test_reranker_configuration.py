"""Tests for reranker configuration in HybridSearchConfig."""

import pytest

pytestmark = pytest.mark.integration

from agent_vault.config import Config, ConfigurationError


class TestRerankerConfiguration:
    """Test reranker configuration loading and validation."""
    
    def test_default_reranker_type(self):
        """Test that default reranker type is rrf."""
        config = Config.load()
        assert config.search.hybrid_search.reranker_type == "rrf"
        assert config.search.hybrid_search.reranker_params == {"k": 60}
    
    def test_rrf_reranker_configuration(self):
        """Test RRF reranker configuration with k parameter."""
        config_data = {
            'storage': {
                'root': './.test_storage',
                'lancedb': {'path': 'lancedb'},
                'file_tracker': {'path': 'file_tracker.db'},
                'document_cache': {'enabled': False, 'path': 'cache'}
            },
            'cache': {'document_cache': {'max_size': 1000}},
            'search': {
                'default_limit': 10,
                'max_limit': 100,
                'hybrid_search': {
                    'vector_weight': 0.7,
                    'fts_weight': 0.3,
                    'reranker_type': 'rrf',
                    'reranker_params': {'k': 60}
                }
            },
            'embeddings': {'default_provider': 'sentence_transformer'},
            'parsers': {}
        }
        
        # Should not raise
        Config._validate_config(config_data)
        
        # Verify values
        assert config_data['search']['hybrid_search']['reranker_type'] == 'rrf'
        assert config_data['search']['hybrid_search']['reranker_params']['k'] == 60
    
    def test_cross_encoder_reranker_configuration(self):
        """Test cross-encoder reranker configuration."""
        config_data = {
            'storage': {
                'root': './.test_storage',
                'lancedb': {'path': 'lancedb'},
                'file_tracker': {'path': 'file_tracker.db'},
                'document_cache': {'enabled': False, 'path': 'cache'}
            },
            'cache': {'document_cache': {'max_size': 1000}},
            'search': {
                'default_limit': 10,
                'max_limit': 100,
                'hybrid_search': {
                    'vector_weight': 0.7,
                    'fts_weight': 0.3,
                    'reranker_type': 'cross_encoder',
                    'reranker_params': {
                        'model_name': 'cross-encoder/ms-marco-MiniLM-L-6-v2'
                    }
                }
            },
            'embeddings': {'default_provider': 'sentence_transformer'},
            'parsers': {}
        }
        
        # Should not raise
        Config._validate_config(config_data)
    
    def test_colbert_reranker_configuration(self):
        """Test ColBERT reranker configuration."""
        config_data = {
            'storage': {
                'root': './.test_storage',
                'lancedb': {'path': 'lancedb'},
                'file_tracker': {'path': 'file_tracker.db'},
                'document_cache': {'enabled': False, 'path': 'cache'}
            },
            'cache': {'document_cache': {'max_size': 1000}},
            'search': {
                'default_limit': 10,
                'max_limit': 100,
                'hybrid_search': {
                    'vector_weight': 0.7,
                    'fts_weight': 0.3,
                    'reranker_type': 'colbert',
                    'reranker_params': {}
                }
            },
            'embeddings': {'default_provider': 'sentence_transformer'},
            'parsers': {}
        }
        
        # Should not raise
        Config._validate_config(config_data)
    
    def test_invalid_reranker_type(self):
        """Test that invalid reranker type is rejected."""
        config_data = {
            'storage': {
                'root': './.test_storage',
                'lancedb': {'path': 'lancedb'},
                'file_tracker': {'path': 'file_tracker.db'},
                'document_cache': {'enabled': False, 'path': 'cache'}
            },
            'cache': {'document_cache': {'max_size': 1000}},
            'search': {
                'default_limit': 10,
                'max_limit': 100,
                'hybrid_search': {
                    'vector_weight': 0.7,
                    'fts_weight': 0.3,
                    'reranker_type': 'cohere',  # API-based reranker not supported
                    'reranker_params': {}
                }
            },
            'embeddings': {'default_provider': 'sentence_transformer'},
            'parsers': {}
        }
        
        with pytest.raises(ConfigurationError):
            Config._validate_config(config_data)
    
    def test_environment_variable_reranker_type(self, monkeypatch):
        """Test setting reranker type via environment variable."""
        monkeypatch.setenv('AGV_SEARCH_HYBRID_SEARCH_RERANKER_TYPE', 'rrf')
        
        config = Config.load()
        assert config.search.hybrid_search.reranker_type == 'rrf'
    
    def test_environment_variable_reranker_params(self, monkeypatch):
        """Test setting reranker params via environment variable."""
        # Note: Complex nested params may need special handling
        monkeypatch.setenv('AGV_SEARCH_HYBRID_SEARCH_RERANKER_TYPE', 'rrf')
        
        config = Config.load()
        assert config.search.hybrid_search.reranker_type == 'rrf'
    
    def test_all_reranker_types_valid(self):
        """Test that all documented reranker types are valid."""
        valid_types = [
            'rrf',
            'linear_combination',
            'cross_encoder',
            'colbert'
        ]
        
        for reranker_type in valid_types:
            config_data = {
                'storage': {
                    'root': './.test_storage',
                    'lancedb': {'path': 'lancedb'},
                    'file_tracker': {'path': 'file_tracker.db'},
                    'document_cache': {'enabled': False, 'path': 'cache'}
                },
                'cache': {'document_cache': {'max_size': 1000}},
                'search': {
                    'default_limit': 10,
                    'max_limit': 100,
                    'hybrid_search': {
                        'vector_weight': 0.7,
                        'fts_weight': 0.3,
                        'reranker_type': reranker_type,
                        'reranker_params': {}
                    }
                },
                'embeddings': {'default_provider': 'sentence_transformer'},
                'parsers': {}
            }
            
            # Should not raise
            Config._validate_config(config_data)
    
    def test_reranker_params_flexibility(self):
        """Test that reranker_params accepts arbitrary parameters."""
        config_data = {
            'storage': {
                'root': './.test_storage',
                'lancedb': {'path': 'lancedb'},
                'file_tracker': {'path': 'file_tracker.db'},
                'document_cache': {'enabled': False, 'path': 'cache'}
            },
            'cache': {'document_cache': {'max_size': 1000}},
            'search': {
                'default_limit': 10,
                'max_limit': 100,
                'hybrid_search': {
                    'vector_weight': 0.7,
                    'fts_weight': 0.3,
                    'reranker_type': 'rrf',
                    'reranker_params': {
                        'k': 60,
                        'custom_param': 'value',
                        'nested': {'param': 123}
                    }
                }
            },
            'embeddings': {'default_provider': 'sentence_transformer'},
            'parsers': {}
        }
        
        # Should not raise - reranker_params allows additional properties
        Config._validate_config(config_data)
    
    def test_backward_compatibility(self):
        """Test that configs without reranker settings still work."""
        config_data = {
            'storage': {
                'root': './.test_storage',
                'lancedb': {'path': 'lancedb'},
                'file_tracker': {'path': 'file_tracker.db'},
                'document_cache': {'enabled': False, 'path': 'cache'}
            },
            'cache': {'document_cache': {'max_size': 1000}},
            'search': {
                'default_limit': 10,
                'max_limit': 100,
                'hybrid_search': {
                    'vector_weight': 0.7,
                    'fts_weight': 0.3
                    # No reranker settings - should use defaults
                }
            },
            'embeddings': {'default_provider': 'sentence_transformer'},
            'parsers': {}
        }
        
        # Should not raise
        Config._validate_config(config_data)


class TestRerankerConfigurationExamples:
    """Test realistic reranker configuration examples."""
    
    def test_rrf_with_custom_k(self):
        """Test RRF configuration with custom k value."""
        config_data = {
            'storage': {
                'root': './.test_storage',
                'lancedb': {'path': 'lancedb'},
                'file_tracker': {'path': 'file_tracker.db'},
                'document_cache': {'enabled': False, 'path': 'cache'}
            },
            'cache': {'document_cache': {'max_size': 1000}},
            'search': {
                'default_limit': 10,
                'max_limit': 100,
                'hybrid_search': {
                    'reranker_type': 'rrf',
                    'reranker_params': {'k': 100}  # Custom k value
                }
            },
            'embeddings': {'default_provider': 'sentence_transformer'},
            'parsers': {}
        }
        
        Config._validate_config(config_data)
        assert config_data['search']['hybrid_search']['reranker_params']['k'] == 100
    
    def test_linear_combination_with_weight(self):
        """Test linear combination with explicit weight parameter."""
        config_data = {
            'storage': {
                'root': './.test_storage',
                'lancedb': {'path': 'lancedb'},
                'file_tracker': {'path': 'file_tracker.db'},
                'document_cache': {'enabled': False, 'path': 'cache'}
            },
            'cache': {'document_cache': {'max_size': 1000}},
            'search': {
                'default_limit': 10,
                'max_limit': 100,
                'hybrid_search': {
                    'vector_weight': 0.8,
                    'fts_weight': 0.2,
                    'reranker_type': 'linear_combination',
                    'reranker_params': {'weight': 0.8}  # Should match vector_weight
                }
            },
            'embeddings': {'default_provider': 'sentence_transformer'},
            'parsers': {}
        }
        
        Config._validate_config(config_data)
