"""Tests for FastEmbed embedder implementation."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from agentic_inquiry.embeddings.fastembed import FastEmbedEmbedder


@pytest.mark.unit
class TestFastEmbedEmbedder:
    """Tests for FastEmbedEmbedder class."""

    @pytest.fixture
    def mock_text_embedding(self):
        """Mock the TextEmbedding class from fastembed."""
        with patch("fastembed.TextEmbedding") as mock_cls:
            mock_instance = mock_cls.return_value
            # Mock the underlying model to provide dimensions
            mock_instance.model = MagicMock()
            mock_instance.model.model_out_channels = 384
            
            # Mock passage_embed to return a generator of numpy arrays
            def mock_passage_embed(texts, batch_size=32, parallel=None):
                for _ in texts:
                    yield np.random.rand(384).astype(np.float32)
            
            mock_instance.passage_embed.side_effect = mock_passage_embed
            yield mock_cls

    def test_initialization(self):
        """Test that the embedder initializes with correct parameters."""
        embedder = FastEmbedEmbedder(
            model_name="BAAI/bge-small-en-v1.5",
            batch_size=64,
            threads=4
        )
        
        assert embedder.model_name == "BAAI/bge-small-en-v1.5"
        assert embedder.batch_size == 64
        assert embedder.threads == 4
        assert embedder._model is None

    def test_ndims_lazy_loading(self, mock_text_embedding):
        """Test that ndims() triggers lazy loading and returns correct dimensions."""
        embedder = FastEmbedEmbedder(model_name="BAAI/bge-small-en-v1.5")
        
        # Should be None initially
        assert embedder._ndims is None
        
        # Calling ndims() should trigger load
        dims = embedder.ndims()
        
        assert dims == 384
        assert embedder._ndims == 384
        mock_text_embedding.assert_called_once()

    def test_generate(self, mock_text_embedding):
        """Test generating embeddings for a batch of texts."""
        embedder = FastEmbedEmbedder(model_name="BAAI/bge-small-en-v1.5")
        texts = ["hello world", "testing fastembed"]
        
        embeddings = embedder.generate(texts)
        
        assert len(embeddings) == 2
        assert len(embeddings[0]) == 384
        assert isinstance(embeddings[0], list)
        assert isinstance(embeddings[0][0], float)
        
        # Verify mock was called with correct parameters
        mock_instance = mock_text_embedding.return_value
        mock_instance.passage_embed.assert_called_once_with(
            texts,
            batch_size=32,
            parallel=None
        )

    @pytest.mark.asyncio
    async def test_generate_async(self, mock_text_embedding):
        """Test generating embeddings asynchronously."""
        embedder = FastEmbedEmbedder(model_name="BAAI/bge-small-en-v1.5")
        texts = ["async hello", "async world"]
        
        embeddings = await embedder.generate_async(texts)
        
        assert len(embeddings) == 2
        assert len(embeddings[0]) == 384
        
        # Verify mock was called
        mock_instance = mock_text_embedding.return_value
        mock_instance.passage_embed.assert_called_once()

    def test_ensure_model_loaded(self, mock_text_embedding):
        """Test that ensure_model_loaded manually triggers loading."""
        embedder = FastEmbedEmbedder(model_name="BAAI/bge-small-en-v1.5")
        
        assert embedder._model is None
        embedder.ensure_model_loaded()
        assert embedder._model is not None
        mock_text_embedding.assert_called_once()

    def test_import_error_handling(self):
        """Test that a descriptive ImportError is raised if fastembed is missing."""
        with patch("fastembed.TextEmbedding", side_effect=ImportError):
            embedder = FastEmbedEmbedder()
            with pytest.raises(ImportError, match="fastembed is required"):
                embedder.generate(["test"])
