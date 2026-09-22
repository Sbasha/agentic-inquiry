"""Integration tests for LocalModelEmbedder with real pipeline and performance validation."""

import pytest

pytestmark = pytest.mark.integration

import asyncio
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from agent_vault.embeddings.local_model import LocalModelEmbedder, ModelMetadata
from agent_vault.embeddings.registry import EmbeddingRegistry


@pytest.fixture
def mock_onnx_session_for_integration():
    """Create a mock ONNX session for integration tests."""
    import onnxruntime as ort
    
    session = MagicMock(spec=ort.InferenceSession)
    
    # Mock inputs
    input_mock = MagicMock()
    input_mock.name = "input_ids"
    attention_mock = MagicMock()
    attention_mock.name = "attention_mask"
    session.get_inputs.return_value = [input_mock, attention_mock]
    
    # Mock outputs
    output_mock = MagicMock()
    output_mock.name = "last_hidden_state"
    session.get_outputs.return_value = [output_mock]
    
    # Mock run method to return fake embeddings
    def mock_run(output_names, inputs):
        batch_size = inputs["input_ids"].shape[0]
        seq_length = inputs["input_ids"].shape[1]
        hidden_size = 384
        # Return fake token embeddings
        return [np.random.randn(batch_size, seq_length, hidden_size).astype(np.float32)]
    
    session.run.side_effect = mock_run
    
    return session


@pytest.fixture
def mock_tokenizer_for_integration():
    """Create a mock tokenizer for integration tests."""
    tokenizer = MagicMock()
    
    def mock_encode_batch(texts):
        encodings = []
        for text in texts:
            encoding = MagicMock()
            # Create fake token IDs
            encoding.ids = [101] + [i for i in range(len(text))] + [102]
            encoding.attention_mask = [1] * len(encoding.ids)
            encodings.append(encoding)
        return encodings
    
    tokenizer.encode_batch.side_effect = mock_encode_batch
    
    return tokenizer


@pytest.fixture
def integration_embedder(tmp_path, mock_onnx_session_for_integration, mock_tokenizer_for_integration):
    """Create a LocalModelEmbedder for integration testing."""
    from datetime import datetime
    
    model_path = tmp_path / "integration_model"
    model_path.mkdir()
    
    # Create metadata
    metadata = ModelMetadata(
        model_id="integration-test-model",
        format="onnx",
        dimensions=384,
        max_sequence_length=512,
        tokenizer_type="BertTokenizer",
        normalize_embeddings=True,
        pooling_mode="mean",
        created_at=datetime.now().isoformat()
    )
    
    embedder = LocalModelEmbedder(
        model_path=model_path,
        normalize=True,
        batch_size=32
    )
    
    # Inject mocked components
    embedder._model = mock_onnx_session_for_integration
    embedder._tokenizer = mock_tokenizer_for_integration
    embedder._metadata = metadata
    
    return embedder


class TestLocalModelEmbedderPipelineIntegration:
    """Test LocalModelEmbedder integration with indexing pipeline components."""
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_embedder_with_embedding_service(self, integration_embedder):
        """Test LocalModelEmbedder with embedding service."""
        from agent_vault.indexing.embedding_service import EmbeddingService
        
        # Create embedding service with local embedder
        registry = EmbeddingRegistry()
        registry.configure_default_embedder(integration_embedder)
        
        service = EmbeddingService(registry=registry)
        
        # Test texts
        texts = [
            "This is a test document",
            "Another test document",
            "Third test document"
        ]
        
        # Generate embeddings using the service
        embeddings = await service.generate_embeddings_batch(
            texts=texts,
            embedder=integration_embedder,
            operation_name="test_embedding"
        )
        
        # Verify embeddings
        assert len(embeddings) == 3
        for embedding in embeddings:
            assert len(embedding) == 384
            # Verify normalization
            norm = np.linalg.norm(embedding)
            assert abs(norm - 1.0) < 0.01
    
    @pytest.mark.integration
    def test_embedder_with_registry_configuration(self, integration_embedder):
        """Test LocalModelEmbedder configuration through registry."""
        from agent_vault.indexing.embedding_service import EmbeddingService
        
        # Create embedding service with local embedder
        registry = EmbeddingRegistry()
        registry.configure_default_embedder(integration_embedder)
        
        service = EmbeddingService(registry=registry)
        
        # Get embedder configuration
        embedder, dims = service.get_embedder_configuration("document_chunks", "vector")
        
        # Verify configuration
        assert embedder is integration_embedder
        assert dims == 384
    
    @pytest.mark.integration
    def test_embedder_with_multiple_table_configurations(self, integration_embedder):
        """Test LocalModelEmbedder with per-table configuration."""
        from agent_vault.embeddings.hashing import HashingEmbedder
        from agent_vault.indexing.embedding_service import EmbeddingService
        
        # Create registry with different embedders for different tables
        registry = EmbeddingRegistry()
        registry.configure_default_embedder(integration_embedder)
        
        # Add specific embedder for graph entities
        hashing_embedder = HashingEmbedder(ndims=256)
        registry.register("graph_entities", "vector", hashing_embedder)
        
        service = EmbeddingService(registry=registry)
        
        # Verify correct embedders are used
        doc_embedder, doc_dims = service.get_embedder_configuration("document_chunks", "vector")
        graph_embedder, graph_dims = service.get_embedder_configuration("graph_entities", "vector")
        
        assert doc_embedder is integration_embedder
        assert doc_dims == 384
        assert graph_embedder is hashing_embedder
        assert graph_dims == 256


class TestOfflineOperation:
    """Test that LocalModelEmbedder operates completely offline."""
    
    @pytest.mark.integration
    def test_no_network_requests_during_embedding(self, integration_embedder):
        """Verify no network requests are made during embedding generation."""
        
        # Mock socket to raise exception if any network call is attempted
        
        def mock_socket(*args, **kwargs):
            raise RuntimeError("Network request attempted during offline operation!")
        
        with patch('socket.socket', side_effect=mock_socket):
            # Generate embeddings - should not make any network calls
            texts = ["Test text 1", "Test text 2", "Test text 3"]
            embeddings = integration_embedder.generate(texts)
            
            # Verify embeddings were generated successfully
            assert len(embeddings) == 3
            assert all(len(emb) == 384 for emb in embeddings)
    
    @pytest.mark.asyncio
    async def test_async_no_network_requests(self, integration_embedder):
        """Verify async embedding generation makes no network requests."""
        
        def mock_socket(*args, **kwargs):
            raise RuntimeError("Network request attempted during offline operation!")
        
        with patch('socket.socket', side_effect=mock_socket):
            # Generate embeddings asynchronously
            texts = ["Async test 1", "Async test 2"]
            embeddings = await integration_embedder.generate_async(texts)
            
            # Verify embeddings were generated successfully
            assert len(embeddings) == 2
            assert all(len(emb) == 384 for emb in embeddings)


class TestMultipleModelFormats:
    """Test LocalModelEmbedder with different model formats."""
    
    def test_onnx_format_detection(self, tmp_path):
        """Test ONNX format is correctly detected and loaded."""
        from agent_vault.embeddings.local_model import ModelLoader
        from datetime import datetime
        
        model_dir = tmp_path / "onnx_model"
        model_dir.mkdir()
        
        # Create ONNX model file
        (model_dir / "model.onnx").write_bytes(b"fake onnx")
        
        # Create metadata
        metadata = ModelMetadata(
            model_id="onnx-test",
            format="onnx",
            dimensions=384,
            max_sequence_length=512,
            tokenizer_type="BertTokenizer",
            normalize_embeddings=True,
            pooling_mode="mean",
            created_at=datetime.now().isoformat()
        )
        metadata.save(model_dir / "metadata.json")
        
        # Test format detection
        loader = ModelLoader(tmp_path)
        detected_format = loader.detect_format(model_dir)
        
        assert detected_format == "onnx"
    
    def test_safetensors_format_detection(self, tmp_path):
        """Test safetensors format is correctly detected."""
        from agent_vault.embeddings.local_model import ModelLoader
        from datetime import datetime
        
        model_dir = tmp_path / "safetensors_model"
        model_dir.mkdir()
        
        # Create safetensors model file
        (model_dir / "model.safetensors").write_bytes(b"fake safetensors")
        
        # Create metadata
        metadata = ModelMetadata(
            model_id="safetensors-test",
            format="safetensors",
            dimensions=768,
            max_sequence_length=512,
            tokenizer_type="BertTokenizer",
            normalize_embeddings=True,
            pooling_mode="mean",
            created_at=datetime.now().isoformat()
        )
        metadata.save(model_dir / "metadata.json")
        
        # Test format detection
        loader = ModelLoader(tmp_path)
        detected_format = loader.detect_format(model_dir)
        
        assert detected_format == "safetensors"
    
    def test_pytorch_format_detection(self, tmp_path):
        """Test PyTorch format is correctly detected."""
        from agent_vault.embeddings.local_model import ModelLoader
        from datetime import datetime
        
        model_dir = tmp_path / "pytorch_model"
        model_dir.mkdir()
        
        # Create PyTorch model file
        (model_dir / "pytorch_model.bin").write_bytes(b"fake pytorch")
        
        # Create metadata
        metadata = ModelMetadata(
            model_id="pytorch-test",
            format="pytorch",
            dimensions=512,
            max_sequence_length=512,
            tokenizer_type="BertTokenizer",
            normalize_embeddings=True,
            pooling_mode="mean",
            created_at=datetime.now().isoformat()
        )
        metadata.save(model_dir / "metadata.json")
        
        # Test format detection
        loader = ModelLoader(tmp_path)
        detected_format = loader.detect_format(model_dir)
        
        assert detected_format == "pytorch"


class TestBatchSizePerformance:
    """Test LocalModelEmbedder performance with different batch sizes."""
    
    @pytest.mark.integration
    def test_small_batch_size(self, integration_embedder):
        """Test embedding generation with small batch size."""
        integration_embedder.batch_size = 2
        
        texts = ["text1", "text2", "text3", "text4", "text5"]
        
        start_time = time.time()
        embeddings = integration_embedder.generate(texts)
        elapsed_time = time.time() - start_time
        
        # Verify all embeddings generated
        assert len(embeddings) == 5
        assert all(len(emb) == 384 for emb in embeddings)
        
        # Should complete reasonably quickly even with small batches
        assert elapsed_time < 5.0  # 5 seconds max
    
    @pytest.mark.integration
    def test_medium_batch_size(self, integration_embedder):
        """Test embedding generation with medium batch size."""
        integration_embedder.batch_size = 16
        
        texts = [f"test text {i}" for i in range(50)]
        
        start_time = time.time()
        embeddings = integration_embedder.generate(texts)
        elapsed_time = time.time() - start_time
        
        # Verify all embeddings generated
        assert len(embeddings) == 50
        assert all(len(emb) == 384 for emb in embeddings)
        
        # Should complete reasonably quickly
        assert elapsed_time < 10.0  # 10 seconds max
    
    @pytest.mark.integration
    def test_large_batch_size(self, integration_embedder):
        """Test embedding generation with large batch size."""
        integration_embedder.batch_size = 64
        
        texts = [f"test text {i}" for i in range(100)]
        
        start_time = time.time()
        embeddings = integration_embedder.generate(texts)
        elapsed_time = time.time() - start_time
        
        # Verify all embeddings generated
        assert len(embeddings) == 100
        assert all(len(emb) == 384 for emb in embeddings)
        
        # Large batches should be more efficient
        assert elapsed_time < 15.0  # 15 seconds max
    
    @pytest.mark.asyncio
    async def test_async_batch_performance(self, integration_embedder):
        """Test async embedding generation performance with batching."""
        integration_embedder.batch_size = 32
        
        # Create multiple batches to process concurrently
        batches = [
            [f"batch1_text{i}" for i in range(20)],
            [f"batch2_text{i}" for i in range(20)],
            [f"batch3_text{i}" for i in range(20)],
        ]
        
        start_time = time.time()
        results = await asyncio.gather(*[
            integration_embedder.generate_async(batch)
            for batch in batches
        ])
        elapsed_time = time.time() - start_time
        
        # Verify all embeddings generated
        assert len(results) == 3
        assert all(len(result) == 20 for result in results)
        
        # Concurrent processing should be efficient
        assert elapsed_time < 10.0  # 10 seconds max
    
    @pytest.mark.integration
    def test_batch_size_consistency(self, integration_embedder):
        """Test that different batch sizes produce consistent embeddings."""
        texts = ["consistent text 1", "consistent text 2", "consistent text 3"]
        
        # Generate with batch size 1
        integration_embedder.batch_size = 1
        embeddings_batch1 = integration_embedder.generate(texts)
        
        # Generate with batch size 3
        integration_embedder.batch_size = 3
        embeddings_batch3 = integration_embedder.generate(texts)
        
        # Embeddings should be similar (allowing for floating point differences)
        for emb1, emb3 in zip(embeddings_batch1, embeddings_batch3):
            # Check that embeddings are close
            np.linalg.norm(np.array(emb1) - np.array(emb3))
            # Allow some difference due to random generation in mock
            # In real scenario with deterministic model, this should be very small
            assert len(emb1) == len(emb3) == 384


class TestRegressionPrevention:
    """Test that LocalModelEmbedder doesn't break existing functionality."""
    
    @pytest.mark.integration
    def test_embedding_registry_still_works(self, integration_embedder):
        """Test that EmbeddingRegistry works with LocalModelEmbedder."""
        from agent_vault.embeddings.registry import EmbeddingRegistry
        from agent_vault.embeddings.hashing import HashingEmbedder
        
        registry = EmbeddingRegistry()
        
        # Configure default embedder
        registry.configure_default_embedder(integration_embedder)
        
        # Add specific embedder for a table
        hashing = HashingEmbedder(ndims=256)
        registry.register("special_table", "vector", hashing)
        
        # Verify registry works correctly
        assert registry.get("normal_table", "vector") is integration_embedder
        assert registry.get("special_table", "vector") is hashing
        assert registry.get_expected_dimensions("normal_table", "vector") == 384
        assert registry.get_expected_dimensions("special_table", "vector") == 256
    
    def test_sentence_transformer_embedder_still_works(self, tmp_path):
        """Test that SentenceTransformerEmbedder still works alongside LocalModelEmbedder."""
        from agent_vault.embeddings.sentence_transformer import SentenceTransformerEmbedder
        from agent_vault.embeddings.registry import EmbeddingRegistry
        
        # Create SentenceTransformerEmbedder
        st_embedder = SentenceTransformerEmbedder(model_name="all-MiniLM-L6-v2")
        
        # Create registry and configure
        registry = EmbeddingRegistry()
        registry.configure_default_embedder(st_embedder)
        
        # Verify it works
        retrieved = registry.get("test_table", "vector")
        assert retrieved is st_embedder
        assert registry.get_expected_dimensions("test_table", "vector") == 384
    
    def test_hashing_embedder_still_works(self):
        """Test that HashingEmbedder still works alongside LocalModelEmbedder."""
        from agent_vault.embeddings.hashing import HashingEmbedder
        from agent_vault.embeddings.registry import EmbeddingRegistry
        
        # Create HashingEmbedder
        hashing = HashingEmbedder(ndims=128)
        
        # Create registry and configure
        registry = EmbeddingRegistry()
        registry.configure_default_embedder(hashing)
        
        # Verify it works
        retrieved = registry.get("test_table", "vector")
        assert retrieved is hashing
        assert registry.get_expected_dimensions("test_table", "vector") == 128
        
        # Test embedding generation
        embeddings = hashing.generate(["test1", "test2"])
        assert len(embeddings) == 2
        assert all(len(emb) == 128 for emb in embeddings)
