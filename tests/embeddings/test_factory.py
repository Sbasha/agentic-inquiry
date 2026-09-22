"""Tests for embedder direct instantiation."""

import pytest

pytestmark = pytest.mark.integration

from agentic_inquiry.config import Config
from agentic_inquiry.embeddings.base import Embedder
from agentic_inquiry.embeddings.sentence_transformer import SentenceTransformerEmbedder
from agentic_inquiry.embeddings.hashing import HashingEmbedder


class TestEmbedderInstantiation:
    """Tests for direct embedder instantiation."""
    
    def test_create_sentence_transformer_embedder(self):
        """Test creating sentence transformer embedder."""
        config = Config.load()
        st_config = config.embeddings.sentence_transformer
        embedder = SentenceTransformerEmbedder(
            model_name=st_config.model_name,
            ndims=st_config.ndims
        )
        
        assert isinstance(embedder, SentenceTransformerEmbedder)
        assert isinstance(embedder, Embedder)
        assert embedder.ndims() > 0
    
    @pytest.mark.smoke
    def test_create_hashing_embedder(self):
        """Test creating hashing embedder."""
        config = Config.load()
        embedder = HashingEmbedder(ndims=config.embeddings.hashing.ndims)
        
        assert isinstance(embedder, HashingEmbedder)
        assert isinstance(embedder, Embedder)
        assert embedder.ndims() == 128  # Default from config
    
    def test_create_embedder_with_default_provider(self, tmp_path):
        """Test creating embedder using default provider from config."""
        # Create a config with default provider
        config = Config.load()
        provider = config.embeddings.default_provider
        
        if provider == "sentence_transformer":
            st_config = config.embeddings.sentence_transformer
            embedder = SentenceTransformerEmbedder(
                model_name=st_config.model_name,
                ndims=st_config.ndims
            )
            assert isinstance(embedder, SentenceTransformerEmbedder)
        elif provider == "hashing":
            embedder = HashingEmbedder(ndims=config.embeddings.hashing.ndims)
            assert isinstance(embedder, HashingEmbedder)
    
    def test_create_embedder_invalid_dimensions(self):
        """Test that invalid dimensions are handled."""
        # HashingEmbedder accepts any positive integer for ndims
        # Test that we can create embedders with various dimensions
        embedder_small = HashingEmbedder(ndims=32)
        assert embedder_small.ndims() == 32
        
        embedder_large = HashingEmbedder(ndims=1024)
        assert embedder_large.ndims() == 1024
    
    def test_create_embedder_with_custom_config(self, tmp_path):
        """Test creating embedder with custom configuration."""
        Config.load()
        
        # Use custom dimensions
        custom_ndims = 256
        embedder = HashingEmbedder(ndims=custom_ndims)
        
        assert isinstance(embedder, HashingEmbedder)
        assert embedder.ndims() == 256
    
    def test_create_embedder_integration_with_registry(self):
        """Test that directly instantiated embedder works with EmbeddingRegistry."""
        from agentic_inquiry.embeddings.registry import EmbeddingRegistry
        
        # Create embedder with direct instantiation
        config = Config.load()
        embedder = HashingEmbedder(ndims=config.embeddings.hashing.ndims)
        
        # Register with registry
        registry = EmbeddingRegistry()
        registry.configure_default_embedder(embedder)
        
        # Verify it can be retrieved
        retrieved_embedder = registry.get("test_table", "test_column")
        assert retrieved_embedder is embedder
        assert registry.get_expected_dimensions("test_table", "test_column") == 128
