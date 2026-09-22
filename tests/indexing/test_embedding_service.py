"""Tests for EmbeddingService component."""

import pytest

pytestmark = pytest.mark.unit

from agent_vault.embeddings.registry import EmbeddingRegistry
from agent_vault.exceptions import StorageError
from agent_vault.indexing.embedding_service import EmbeddingService


class _DummyEmbedder:
    """Dummy embedder for testing."""
    
    def ndims(self):
        """Return embedding dimensions."""
        return 128
    
    def generate(self, texts):
        """Generate dummy embeddings."""
        return [[0.1] * 128 for _ in texts]


class _FailingEmbedder:
    """Embedder that fails on batch but succeeds on individual."""
    
    def __init__(self):
        self.call_count = 0
    
    def ndims(self):
        """Return embedding dimensions."""
        return 128
    
    def generate(self, texts):
        """Fail on first call (batch), succeed on subsequent calls (individual)."""
        self.call_count += 1
        if self.call_count == 1:
            raise RuntimeError("Batch generation failed")
        return [[0.1] * 128 for _ in texts]


class _CompletelyFailingEmbedder:
    """Embedder that always fails."""
    
    def ndims(self):
        """Return embedding dimensions."""
        return 128
    
    def generate(self, texts):
        """Always fail."""
        raise RuntimeError("Embedding generation failed")


@pytest.mark.asyncio
class TestEmbeddingService:
    """Test suite for EmbeddingService."""
    
    async def test_get_embedder_configuration(self):
        """Test getting embedder configuration from registry."""
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        service = EmbeddingService(registry=registry)
        
        embedder, dims = service.get_embedder_configuration("document_chunks", "vector")

        assert embedder is not None
        assert isinstance(embedder, _DummyEmbedder)
        assert dims == 128  # Default dimension
    
    async def test_generate_embeddings_batch_success(self):
        """Test successful batch embedding generation."""
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        service = EmbeddingService(registry=registry)
        
        embedder, _ = service.get_embedder_configuration("document_chunks", "vector")
        texts = ["text1", "text2", "text3"]
        
        vectors = await service.generate_embeddings_batch(texts, embedder)
        
        assert len(vectors) == 3
        assert all(len(v) == 128 for v in vectors)
    
    async def test_generate_embeddings_batch_empty_input(self):
        """Test batch generation with empty input."""
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        service = EmbeddingService(registry=registry)
        
        embedder, _ = service.get_embedder_configuration("document_chunks", "vector")
        
        vectors = await service.generate_embeddings_batch([], embedder)
        
        assert vectors == []
    
    async def test_generate_embeddings_batch_fallback_to_individual(self):
        """Test fallback to individual generation when batch fails."""
        registry = EmbeddingRegistry(default_embedder=_FailingEmbedder())
        service = EmbeddingService(registry=registry)
        
        embedder, _ = service.get_embedder_configuration("document_chunks", "vector")
        texts = ["text1", "text2"]
        
        # Should succeed via fallback
        vectors = await service.generate_embeddings_batch(texts, embedder)
        
        assert len(vectors) == 2
        assert all(len(v) == 128 for v in vectors)
        # Verify fallback was used (1 batch call + 2 individual calls)
        assert embedder.call_count == 3
    
    async def test_generate_embeddings_batch_complete_failure(self):
        """Test complete failure when both batch and individual fail."""
        registry = EmbeddingRegistry(default_embedder=_CompletelyFailingEmbedder())
        service = EmbeddingService(registry=registry)
        
        embedder, _ = service.get_embedder_configuration("document_chunks", "vector")
        texts = ["text1"]
        
        with pytest.raises(StorageError, match="Embedding generation failed"):
            await service.generate_embeddings_batch(texts, embedder)
    
    async def test_generate_embeddings_batch_custom_operation_name(self):
        """Test batch generation with custom operation name."""
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        service = EmbeddingService(registry=registry)
        
        embedder, _ = service.get_embedder_configuration("graph_entities", "vector")
        texts = ["entity1"]
        
        vectors = await service.generate_embeddings_batch(
            texts, embedder, operation_name="entity embedding"
        )
        
        assert len(vectors) == 1
        assert len(vectors[0]) == 128
