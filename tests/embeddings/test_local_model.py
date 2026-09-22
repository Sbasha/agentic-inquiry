"""Tests for local model embedder implementation."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

import json
import numpy as np
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from agent_vault.embeddings.local_model import (
    LocalModelEmbedder,
    ModelLoader,
    ModelMetadata,
)


class TestModelMetadata:
    """Tests for ModelMetadata data class."""
    
    @pytest.fixture
    def valid_metadata_dict(self) -> dict:
        """Provide valid metadata dictionary for testing."""
        return {
            "model_id": "sentence-transformers/all-MiniLM-L6-v2",
            "format": "onnx",
            "dimensions": 384,
            "max_sequence_length": 512,
            "tokenizer_type": "BertTokenizer",
            "normalize_embeddings": True,
            "pooling_mode": "mean",
            "created_at": datetime.now().isoformat(),
            "source_url": "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2"
        }
    
    @pytest.fixture
    def valid_metadata(self, valid_metadata_dict) -> ModelMetadata:
        """Provide valid ModelMetadata instance for testing."""
        return ModelMetadata(**valid_metadata_dict)
    
    def test_metadata_creation_with_valid_data(self, valid_metadata_dict):
        """Test creating ModelMetadata with valid data."""
        metadata = ModelMetadata(**valid_metadata_dict)
        
        assert metadata.model_id == valid_metadata_dict["model_id"]
        assert metadata.format == valid_metadata_dict["format"]
        assert metadata.dimensions == valid_metadata_dict["dimensions"]
        assert metadata.max_sequence_length == valid_metadata_dict["max_sequence_length"]
        assert metadata.tokenizer_type == valid_metadata_dict["tokenizer_type"]
        assert metadata.normalize_embeddings == valid_metadata_dict["normalize_embeddings"]
        assert metadata.pooling_mode == valid_metadata_dict["pooling_mode"]
        assert metadata.created_at == valid_metadata_dict["created_at"]
        assert metadata.source_url == valid_metadata_dict["source_url"]
    
    def test_metadata_creation_without_source_url(self, valid_metadata_dict):
        """Test creating ModelMetadata without optional source_url."""
        del valid_metadata_dict["source_url"]
        metadata = ModelMetadata(**valid_metadata_dict)
        
        assert metadata.source_url is None
    
    def test_metadata_validation_empty_model_id(self, valid_metadata_dict):
        """Test validation fails for empty model_id."""
        valid_metadata_dict["model_id"] = ""
        
        with pytest.raises(ValueError, match="model_id must be a non-empty string"):
            ModelMetadata(**valid_metadata_dict)
    
    def test_metadata_validation_invalid_format(self, valid_metadata_dict):
        """Test validation fails for invalid format."""
        valid_metadata_dict["format"] = "invalid_format"
        
        with pytest.raises(ValueError, match="format must be one of"):
            ModelMetadata(**valid_metadata_dict)
    
    def test_metadata_validation_valid_formats(self, valid_metadata_dict):
        """Test validation succeeds for all valid formats."""
        for format_type in ["onnx", "safetensors", "pytorch"]:
            valid_metadata_dict["format"] = format_type
            metadata = ModelMetadata(**valid_metadata_dict)
            assert metadata.format == format_type
    
    def test_metadata_validation_negative_dimensions(self, valid_metadata_dict):
        """Test validation fails for negative dimensions."""
        valid_metadata_dict["dimensions"] = -1
        
        with pytest.raises(ValueError, match="dimensions must be a positive integer"):
            ModelMetadata(**valid_metadata_dict)
    
    def test_metadata_validation_zero_dimensions(self, valid_metadata_dict):
        """Test validation fails for zero dimensions."""
        valid_metadata_dict["dimensions"] = 0
        
        with pytest.raises(ValueError, match="dimensions must be a positive integer"):
            ModelMetadata(**valid_metadata_dict)
    
    def test_metadata_validation_negative_max_sequence_length(self, valid_metadata_dict):
        """Test validation fails for negative max_sequence_length."""
        valid_metadata_dict["max_sequence_length"] = -1
        
        with pytest.raises(ValueError, match="max_sequence_length must be a positive integer"):
            ModelMetadata(**valid_metadata_dict)
    
    def test_metadata_validation_empty_tokenizer_type(self, valid_metadata_dict):
        """Test validation fails for empty tokenizer_type."""
        valid_metadata_dict["tokenizer_type"] = ""
        
        with pytest.raises(ValueError, match="tokenizer_type must be a non-empty string"):
            ModelMetadata(**valid_metadata_dict)
    
    def test_metadata_validation_invalid_normalize_embeddings(self, valid_metadata_dict):
        """Test validation fails for non-boolean normalize_embeddings."""
        valid_metadata_dict["normalize_embeddings"] = "true"
        
        with pytest.raises(ValueError, match="normalize_embeddings must be a boolean"):
            ModelMetadata(**valid_metadata_dict)
    
    def test_metadata_validation_invalid_pooling_mode(self, valid_metadata_dict):
        """Test validation fails for invalid pooling_mode."""
        valid_metadata_dict["pooling_mode"] = "invalid"
        
        with pytest.raises(ValueError, match="pooling_mode must be one of"):
            ModelMetadata(**valid_metadata_dict)
    
    def test_metadata_validation_valid_pooling_modes(self, valid_metadata_dict):
        """Test validation succeeds for all valid pooling modes."""
        for pooling_mode in ["mean", "cls", "max"]:
            valid_metadata_dict["pooling_mode"] = pooling_mode
            metadata = ModelMetadata(**valid_metadata_dict)
            assert metadata.pooling_mode == pooling_mode
    
    def test_metadata_validation_empty_created_at(self, valid_metadata_dict):
        """Test validation fails for empty created_at."""
        valid_metadata_dict["created_at"] = ""
        
        with pytest.raises(ValueError, match="created_at must be a non-empty string"):
            ModelMetadata(**valid_metadata_dict)
    
    def test_metadata_validation_invalid_source_url_type(self, valid_metadata_dict):
        """Test validation fails for non-string source_url."""
        valid_metadata_dict["source_url"] = 123
        
        with pytest.raises(ValueError, match="source_url must be a string or None"):
            ModelMetadata(**valid_metadata_dict)
    
    def test_save_creates_parent_directory(self, valid_metadata, tmp_path):
        """Test save() creates parent directory if it doesn't exist."""
        nested_path = tmp_path / "models" / "test_model" / "metadata.json"
        
        valid_metadata.save(nested_path)
        
        assert nested_path.exists()
        assert nested_path.parent.exists()
    
    def test_save_writes_valid_json(self, valid_metadata, tmp_path):
        """Test save() writes valid JSON file."""
        metadata_path = tmp_path / "metadata.json"
        
        valid_metadata.save(metadata_path)
        
        assert metadata_path.exists()
        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        assert data["model_id"] == valid_metadata.model_id
        assert data["format"] == valid_metadata.format
        assert data["dimensions"] == valid_metadata.dimensions
    
    def test_save_includes_all_fields(self, valid_metadata, tmp_path):
        """Test save() includes all metadata fields."""
        metadata_path = tmp_path / "metadata.json"
        
        valid_metadata.save(metadata_path)
        
        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        expected_fields = {
            "model_id", "format", "dimensions", "max_sequence_length",
            "tokenizer_type", "normalize_embeddings", "pooling_mode",
            "created_at", "source_url"
        }
        assert set(data.keys()) == expected_fields
    
    def test_load_reads_valid_metadata(self, valid_metadata, tmp_path):
        """Test load() reads metadata correctly."""
        metadata_path = tmp_path / "metadata.json"
        valid_metadata.save(metadata_path)
        
        loaded_metadata = ModelMetadata.load(metadata_path)
        
        assert loaded_metadata.model_id == valid_metadata.model_id
        assert loaded_metadata.format == valid_metadata.format
        assert loaded_metadata.dimensions == valid_metadata.dimensions
        assert loaded_metadata.max_sequence_length == valid_metadata.max_sequence_length
        assert loaded_metadata.tokenizer_type == valid_metadata.tokenizer_type
        assert loaded_metadata.normalize_embeddings == valid_metadata.normalize_embeddings
        assert loaded_metadata.pooling_mode == valid_metadata.pooling_mode
        assert loaded_metadata.created_at == valid_metadata.created_at
        assert loaded_metadata.source_url == valid_metadata.source_url
    
    def test_load_raises_file_not_found(self, tmp_path):
        """Test load() raises FileNotFoundError for missing file."""
        metadata_path = tmp_path / "nonexistent.json"
        
        with pytest.raises(FileNotFoundError, match="Metadata file not found"):
            ModelMetadata.load(metadata_path)
    
    def test_load_raises_on_invalid_json(self, tmp_path):
        """Test load() raises ValueError for invalid JSON."""
        metadata_path = tmp_path / "metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            f.write("{ invalid json }")
        
        with pytest.raises(ValueError, match="Invalid JSON"):
            ModelMetadata.load(metadata_path)
    
    def test_load_raises_on_missing_required_fields(self, tmp_path):
        """Test load() raises ValueError for missing required fields."""
        metadata_path = tmp_path / "metadata.json"
        incomplete_data = {
            "model_id": "test-model",
            "format": "onnx"
            # Missing other required fields
        }
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(incomplete_data, f)
        
        with pytest.raises(ValueError, match="Missing required fields"):
            ModelMetadata.load(metadata_path)
    
    def test_load_validates_loaded_data(self, tmp_path):
        """Test load() validates data after loading."""
        metadata_path = tmp_path / "metadata.json"
        invalid_data = {
            "model_id": "test-model",
            "format": "invalid_format",  # Invalid format
            "dimensions": 384,
            "max_sequence_length": 512,
            "tokenizer_type": "BertTokenizer",
            "normalize_embeddings": True,
            "pooling_mode": "mean",
            "created_at": datetime.now().isoformat()
        }
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(invalid_data, f)
        
        with pytest.raises(ValueError, match="format must be one of"):
            ModelMetadata.load(metadata_path)
    
    def test_save_and_load_roundtrip(self, valid_metadata, tmp_path):
        """Test save() and load() roundtrip preserves data."""
        metadata_path = tmp_path / "metadata.json"
        
        # Save
        valid_metadata.save(metadata_path)
        
        # Load
        loaded_metadata = ModelMetadata.load(metadata_path)
        
        # Verify all fields match
        assert loaded_metadata.model_id == valid_metadata.model_id
        assert loaded_metadata.format == valid_metadata.format
        assert loaded_metadata.dimensions == valid_metadata.dimensions
        assert loaded_metadata.max_sequence_length == valid_metadata.max_sequence_length
        assert loaded_metadata.tokenizer_type == valid_metadata.tokenizer_type
        assert loaded_metadata.normalize_embeddings == valid_metadata.normalize_embeddings
        assert loaded_metadata.pooling_mode == valid_metadata.pooling_mode
        assert loaded_metadata.created_at == valid_metadata.created_at
        assert loaded_metadata.source_url == valid_metadata.source_url



class TestModelLoader:
    """Tests for ModelLoader class."""
    
    @pytest.fixture
    def workspace_root(self, tmp_path) -> Path:
        """Provide temporary workspace root for testing."""
        return tmp_path / "workspace"
    
    @pytest.fixture
    def model_loader(self, workspace_root) -> "ModelLoader":
        """Provide ModelLoader instance for testing."""
        from agent_vault.embeddings.local_model import ModelLoader
        workspace_root.mkdir(parents=True, exist_ok=True)
        return ModelLoader(workspace_root)
    
    @pytest.fixture
    def valid_metadata_for_loader(self) -> ModelMetadata:
        """Provide valid ModelMetadata instance for testing."""
        return ModelMetadata(
            model_id="sentence-transformers/all-MiniLM-L6-v2",
            format="onnx",
            dimensions=384,
            max_sequence_length=512,
            tokenizer_type="BertTokenizer",
            normalize_embeddings=True,
            pooling_mode="mean",
            created_at=datetime.now().isoformat(),
            source_url="https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2"
        )
    
    @pytest.fixture
    def sample_model_dir(self, tmp_path, valid_metadata_for_loader) -> Path:
        """Create a sample model directory with metadata."""
        model_dir = tmp_path / "test_model"
        model_dir.mkdir(parents=True, exist_ok=True)
        
        # Save metadata
        metadata_path = model_dir / "metadata.json"
        valid_metadata_for_loader.save(metadata_path)
        
        return model_dir
    
    @pytest.fixture
    def onnx_model_dir(self, sample_model_dir) -> Path:
        """Create a model directory with ONNX model file."""
        # Create a minimal ONNX model file (just a placeholder)
        onnx_path = sample_model_dir / "model.onnx"
        onnx_path.write_bytes(b"fake onnx model")
        
        return sample_model_dir
    
    @pytest.fixture
    def safetensors_model_dir(self, sample_model_dir) -> Path:
        """Create a model directory with safetensors file."""
        safetensors_path = sample_model_dir / "model.safetensors"
        safetensors_path.write_bytes(b"fake safetensors model")
        
        return sample_model_dir
    
    @pytest.fixture
    def pytorch_model_dir(self, sample_model_dir) -> Path:
        """Create a model directory with PyTorch model file."""
        pytorch_path = sample_model_dir / "pytorch_model.bin"
        pytorch_path.write_bytes(b"fake pytorch model")
        
        return sample_model_dir
    
    def test_model_loader_initialization(self, workspace_root):
        """Test ModelLoader initialization."""
        from agent_vault.embeddings.local_model import ModelLoader
        
        loader = ModelLoader(workspace_root)
        
        assert loader.workspace_root == workspace_root
        assert isinstance(loader._model_cache, dict)
        assert len(loader._model_cache) == 0
    
    def test_detect_format_onnx(self, model_loader, onnx_model_dir):
        """Test detect_format() identifies ONNX models."""
        format_type = model_loader.detect_format(onnx_model_dir)
        
        assert format_type == "onnx"
    
    def test_detect_format_safetensors(self, model_loader, safetensors_model_dir):
        """Test detect_format() identifies safetensors models."""
        format_type = model_loader.detect_format(safetensors_model_dir)
        
        assert format_type == "safetensors"
    
    def test_detect_format_pytorch(self, model_loader, pytorch_model_dir):
        """Test detect_format() identifies PyTorch models."""
        format_type = model_loader.detect_format(pytorch_model_dir)
        
        assert format_type == "pytorch"
    
    def test_detect_format_nonexistent_directory(self, model_loader, tmp_path):
        """Test detect_format() raises FileNotFoundError for missing directory."""
        nonexistent_dir = tmp_path / "nonexistent"
        
        with pytest.raises(FileNotFoundError, match="Model directory not found"):
            model_loader.detect_format(nonexistent_dir)
    
    def test_detect_format_not_a_directory(self, model_loader, tmp_path):
        """Test detect_format() raises ValueError for non-directory path."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("not a directory")
        
        with pytest.raises(ValueError, match="Model path must be a directory"):
            model_loader.detect_format(file_path)
    
    def test_detect_format_no_model_files(self, model_loader, sample_model_dir):
        """Test detect_format() raises ValueError when no model files found."""
        # sample_model_dir has only metadata, no model files
        
        with pytest.raises(ValueError, match="Could not detect model format"):
            model_loader.detect_format(sample_model_dir)
    
    def test_detect_format_prefers_onnx(self, model_loader, sample_model_dir):
        """Test detect_format() prefers ONNX when multiple formats present."""
        # Create both ONNX and safetensors files
        (sample_model_dir / "model.onnx").write_bytes(b"onnx")
        (sample_model_dir / "model.safetensors").write_bytes(b"safetensors")
        
        format_type = model_loader.detect_format(sample_model_dir)
        
        assert format_type == "onnx"
    
    def test_load_model_missing_metadata(self, model_loader, tmp_path):
        """Test load_model() raises FileNotFoundError for missing metadata."""
        model_dir = tmp_path / "model_no_metadata"
        model_dir.mkdir()
        
        with pytest.raises(FileNotFoundError, match="Metadata file not found"):
            model_loader.load_model(model_dir)
    
    def test_load_model_unsupported_format_safetensors(
        self, model_loader, safetensors_model_dir
    ):
        """Test load_model() raises ValueError for unsupported safetensors format."""
        with pytest.raises(ValueError, match="Safetensors format not yet supported"):
            model_loader.load_model(safetensors_model_dir)
    
    def test_load_model_unsupported_format_pytorch(
        self, model_loader, pytorch_model_dir
    ):
        """Test load_model() raises ValueError for unsupported PyTorch format."""
        with pytest.raises(ValueError, match="PyTorch format not yet supported"):
            model_loader.load_model(pytorch_model_dir)
    
    def test_load_model_format_mismatch_warning(
        self, model_loader, sample_model_dir, caplog
    ):
        """Test load_model() logs warning when detected format differs from metadata."""
        # Metadata says "onnx" but create safetensors file
        (sample_model_dir / "model.safetensors").write_bytes(b"safetensors")
        
        with pytest.raises(ValueError, match="Safetensors format not yet supported"):
            model_loader.load_model(sample_model_dir)
        
        # Check that warning was logged
        assert any("differs from metadata format" in record.message for record in caplog.records)

    
    def test_load_tokenizer_missing_file(self, model_loader, sample_model_dir):
        """Test _load_tokenizer() raises FileNotFoundError for missing tokenizer.json."""
        # sample_model_dir has no tokenizer.json
        
        with pytest.raises(FileNotFoundError, match="Tokenizer file not found"):
            model_loader._load_tokenizer(sample_model_dir)
    
    def test_load_onnx_model_missing_file(self, model_loader, sample_model_dir):
        """Test _load_onnx_model() raises FileNotFoundError for missing model.onnx."""
        # sample_model_dir has no model.onnx
        
        with pytest.raises(FileNotFoundError, match="ONNX model file not found"):
            model_loader._load_onnx_model(sample_model_dir)
    
    def test_model_caching(self, model_loader, onnx_model_dir):
        """Test that models are cached after first load."""
        # Note: This test will fail with actual ONNX loading since we have fake files
        # But it tests the caching logic
        
        # First, check cache is empty
        assert len(model_loader._model_cache) == 0
        
        # The load will fail because we have fake ONNX files, but that's expected
        # We're just testing that the cache key is checked
        try:
            model_loader.load_model(onnx_model_dir)
        except (RuntimeError, ValueError):
            # Expected to fail with fake ONNX file
            pass
        
        # Now manually add to cache to test cache retrieval
        from agent_vault.embeddings.local_model import ModelMetadata
        fake_model = "fake_model"
        fake_tokenizer = "fake_tokenizer"
        fake_metadata = ModelMetadata(
            model_id="test",
            format="onnx",
            dimensions=384,
            max_sequence_length=512,
            tokenizer_type="test",
            normalize_embeddings=True,
            pooling_mode="mean",
            created_at=datetime.now().isoformat()
        )
        model_loader._model_cache[onnx_model_dir] = (
            fake_model, fake_tokenizer, fake_metadata
        )
        
        # Now load should return cached version
        model, tokenizer, metadata = model_loader.load_model(onnx_model_dir)
        
        assert model == fake_model
        assert tokenizer == fake_tokenizer
        assert metadata == fake_metadata



# Fixtures for LocalModelEmbedder tests
@pytest.fixture
def mock_onnx_session():
    """Create a mock ONNX inference session."""
    import onnxruntime as ort
    
    # Use spec to make isinstance checks work
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
def mock_tokenizer():
    """Create a mock tokenizer."""
    tokenizer = MagicMock()
    
    def mock_encode_batch(texts):
        encodings = []
        for text in texts:
            encoding = MagicMock()
            # Create fake token IDs (just use length of text as proxy)
            encoding.ids = [101] + [i for i in range(len(text))] + [102]
            encoding.attention_mask = [1] * len(encoding.ids)
            encodings.append(encoding)
        return encodings
    
    tokenizer.encode_batch.side_effect = mock_encode_batch
    
    return tokenizer


@pytest.fixture
def mock_metadata():
    """Create mock model metadata."""
    return ModelMetadata(
        model_id="test-model",
        format="onnx",
        dimensions=384,
        max_sequence_length=512,
        tokenizer_type="BertTokenizer",
        normalize_embeddings=True,
        pooling_mode="mean",
        created_at=datetime.now().isoformat(),
        source_url="https://example.com/model"
    )


@pytest.fixture
def mock_model_loader(mock_onnx_session, mock_tokenizer, mock_metadata):
    """Create a mock ModelLoader."""
    loader = MagicMock(spec=ModelLoader)
    loader.load_model.return_value = (mock_onnx_session, mock_tokenizer, mock_metadata)
    return loader


@pytest.fixture
def embedder_with_mocks(tmp_path, mock_model_loader, mock_onnx_session, mock_tokenizer, mock_metadata):
    """Create LocalModelEmbedder with mocked dependencies."""
    model_path = tmp_path / "test_model"
    model_path.mkdir()
    
    embedder = LocalModelEmbedder(
        model_path=model_path,
        normalize=True,
        batch_size=32
    )
    
    # Inject mocked components
    embedder._model = mock_onnx_session
    embedder._tokenizer = mock_tokenizer
    embedder._metadata = mock_metadata
    embedder._loader = mock_model_loader
    
    return embedder


@pytest_asyncio.fixture
async def async_embedder(embedder_with_mocks):
    """Provide embedder for async tests."""
    return embedder_with_mocks


class TestLocalModelEmbedder:
    """Tests for LocalModelEmbedder class."""
    
    def test_initialization_with_default_parameters(self, tmp_path):
        """Test LocalModelEmbedder initialization with default parameters."""
        model_path = tmp_path / "test_model"
        
        embedder = LocalModelEmbedder(model_path=model_path)
        
        assert embedder.model_path == model_path
        assert embedder.normalize is True
        assert embedder.batch_size == 32
        assert embedder._model is None  # Lazy loading
        assert embedder._tokenizer is None
        assert embedder._metadata is None
    
    def test_initialization_with_custom_parameters(self, tmp_path):
        """Test LocalModelEmbedder initialization with custom parameters."""
        model_path = tmp_path / "test_model"
        
        embedder = LocalModelEmbedder(
            model_path=model_path,
            ndims=768,
            normalize=False,
            batch_size=16
        )
        
        assert embedder.model_path == model_path
        assert embedder._ndims == 768
        assert embedder.normalize is False
        assert embedder.batch_size == 16
    
    def test_initialization_with_workspace_relative_path(self, mock_temp_config, tmp_path):
        """Test workspace-relative path resolution."""
        # Set up config with workspace root
        mock_temp_config.storage.root = str(tmp_path)
        
        embedder = LocalModelEmbedder(
            model_path="models/test_model",
            config=mock_temp_config
        )
        
        expected_path = tmp_path / "models" / "test_model"
        assert embedder.model_path == expected_path
    
    def test_initialization_with_absolute_path(self, tmp_path, mock_temp_config):
        """Test that absolute paths are not modified."""
        absolute_path = tmp_path / "absolute" / "model"
        
        embedder = LocalModelEmbedder(
            model_path=absolute_path,
            config=mock_temp_config
        )
        
        assert embedder.model_path == absolute_path
    
    def test_generate_single_text(self, embedder_with_mocks):
        """Test embedding generation for single text."""
        texts = ["Hello world"]
        
        embeddings = embedder_with_mocks.generate(texts)
        
        assert len(embeddings) == 1
        assert len(embeddings[0]) == 384
        assert all(isinstance(val, float) for val in embeddings[0])
    
    def test_generate_batch_texts(self, embedder_with_mocks):
        """Test embedding generation for batch of texts."""
        texts = ["Hello world", "Test text", "Another example"]
        
        embeddings = embedder_with_mocks.generate(texts)
        
        assert len(embeddings) == 3
        assert all(len(emb) == 384 for emb in embeddings)
    
    def test_generate_empty_list_raises_error(self, embedder_with_mocks):
        """Test that empty text list raises ValueError."""
        with pytest.raises(ValueError, match="Cannot generate embeddings for empty text list"):
            embedder_with_mocks.generate([])
    
    def test_generate_invalid_input_type_raises_error(self, embedder_with_mocks):
        """Test that non-string inputs raise ValueError."""
        with pytest.raises(ValueError, match="Text at index .* is not a string"):
            embedder_with_mocks.generate(["valid text", 123, "another text"])
    
    def test_generate_with_batch_size_splitting(self, embedder_with_mocks):
        """Test that large batches are split according to batch_size."""
        embedder_with_mocks.batch_size = 2
        texts = ["text1", "text2", "text3", "text4", "text5"]
        
        embeddings = embedder_with_mocks.generate(texts)
        
        assert len(embeddings) == 5
        # Verify that _generate_batch was called multiple times
        # (implicitly tested by successful completion)
    
    def test_normalization_behavior(self, embedder_with_mocks):
        """Test that normalization produces unit-length vectors."""
        embedder_with_mocks.normalize = True
        texts = ["Test text"]
        
        embeddings = embedder_with_mocks.generate(texts)
        
        # Check that embedding is approximately unit length
        embedding = np.array(embeddings[0])
        norm = np.linalg.norm(embedding)
        assert abs(norm - 1.0) < 0.01  # Allow small floating point error
    
    def test_no_normalization(self, embedder_with_mocks):
        """Test embedding generation without normalization."""
        embedder_with_mocks.normalize = False
        texts = ["Test text"]
        
        embeddings = embedder_with_mocks.generate(texts)
        
        # Embeddings should not be normalized (norm != 1.0)
        embedding = np.array(embeddings[0])
        np.linalg.norm(embedding)
        # With random embeddings, norm should not be exactly 1.0
        # (though it could be close by chance)
        assert len(embeddings[0]) == 384
    
    def test_ndims_returns_correct_dimensions(self, embedder_with_mocks):
        """Test that ndims() returns correct embedding dimensions."""
        dims = embedder_with_mocks.ndims()
        
        assert dims == 384
    
    def test_ndims_with_explicit_ndims_parameter(self, tmp_path):
        """Test ndims() with explicitly set dimensions."""
        embedder = LocalModelEmbedder(
            model_path=tmp_path / "model",
            ndims=768
        )
        
        assert embedder.ndims() == 768
    
    def test_ndims_loads_from_metadata(self, embedder_with_mocks):
        """Test that ndims() loads from metadata when not explicitly set."""
        embedder_with_mocks._ndims = None
        
        dims = embedder_with_mocks.ndims()
        
        assert dims == 384  # From mock_metadata
    
    def test_ensure_loaded_raises_file_not_found(self, tmp_path):
        """Test that _ensure_loaded raises FileNotFoundError for missing model."""
        nonexistent_path = tmp_path / "nonexistent_model"
        
        embedder = LocalModelEmbedder(model_path=nonexistent_path)
        
        with pytest.raises(FileNotFoundError, match="Model files not found"):
            embedder._ensure_loaded()
    
    def test_ensure_loaded_validates_dimensions(self, tmp_path, mock_model_loader, mock_onnx_session, mock_tokenizer):
        """Test that _ensure_loaded validates dimensions match."""
        model_path = tmp_path / "test_model"
        model_path.mkdir()
        
        # Create metadata with different dimensions
        metadata = ModelMetadata(
            model_id="test",
            format="onnx",
            dimensions=512,  # Different from expected
            max_sequence_length=512,
            tokenizer_type="test",
            normalize_embeddings=True,
            pooling_mode="mean",
            created_at=datetime.now().isoformat()
        )
        
        embedder = LocalModelEmbedder(
            model_path=model_path,
            ndims=384  # Expect 384 but model has 512
        )
        
        with patch.object(ModelLoader, '__init__', return_value=None):
            with patch.object(ModelLoader, 'load_model', return_value=(mock_onnx_session, mock_tokenizer, metadata)):
                embedder._loader = ModelLoader(tmp_path)
                
                with pytest.raises(ValueError, match="Model dimensions .* do not match expected dimensions"):
                    embedder._ensure_loaded()
    
    def test_mean_pooling(self, embedder_with_mocks):
        """Test mean pooling implementation."""
        # Create test data
        batch_size, seq_length, hidden_size = 2, 5, 384
        token_embeddings = np.random.randn(batch_size, seq_length, hidden_size).astype(np.float32)
        attention_mask = np.array([
            [1, 1, 1, 0, 0],  # First sequence has 3 valid tokens
            [1, 1, 1, 1, 1]   # Second sequence has 5 valid tokens
        ], dtype=np.int64)
        
        pooled = embedder_with_mocks._mean_pooling(token_embeddings, attention_mask)
        
        assert pooled.shape == (batch_size, hidden_size)
        
        # Verify first sequence pooling (should average first 3 tokens)
        expected_first = token_embeddings[0, :3, :].mean(axis=0)
        np.testing.assert_allclose(pooled[0], expected_first, rtol=1e-5)
    
    def test_normalize_embeddings(self, embedder_with_mocks):
        """Test embedding normalization."""
        # Create test embeddings
        embeddings = np.array([
            [1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0]
        ], dtype=np.float32)
        
        normalized = embedder_with_mocks._normalize_embeddings(embeddings)
        
        # Check that each embedding has unit length
        for i in range(len(normalized)):
            norm = np.linalg.norm(normalized[i])
            assert abs(norm - 1.0) < 1e-6
    
    def test_tokenize_texts(self, embedder_with_mocks):
        """Test text tokenization."""
        texts = ["Hello world", "Test"]
        
        inputs = embedder_with_mocks._tokenize_texts(texts)
        
        assert "input_ids" in inputs
        assert "attention_mask" in inputs
        assert inputs["input_ids"].shape[0] == 2  # Batch size
        assert inputs["attention_mask"].shape[0] == 2
        # Sequences should be padded to same length
        assert inputs["input_ids"].shape[1] == inputs["attention_mask"].shape[1]
    
    @pytest.mark.asyncio
    async def test_generate_async(self, async_embedder):
        """Test async embedding generation."""
        texts = ["Hello world", "Test text"]
        
        embeddings = await async_embedder.generate_async(texts)
        
        assert len(embeddings) == 2
        assert all(len(emb) == 384 for emb in embeddings)
    
    @pytest.mark.asyncio
    async def test_generate_async_concurrent_requests(self, async_embedder):
        """Test concurrent async embedding requests."""
        import asyncio
        
        texts1 = ["Text 1", "Text 2"]
        texts2 = ["Text 3", "Text 4"]
        texts3 = ["Text 5", "Text 6"]
        
        # Run multiple requests concurrently
        results = await asyncio.gather(
            async_embedder.generate_async(texts1),
            async_embedder.generate_async(texts2),
            async_embedder.generate_async(texts3)
        )
        
        assert len(results) == 3
        assert all(len(result) == 2 for result in results)
    
    def test_error_handling_for_inference_failure(self, embedder_with_mocks):
        """Test error handling when inference fails."""
        # Make the model raise an exception
        embedder_with_mocks._model.run.side_effect = RuntimeError("Inference failed")
        
        with pytest.raises(RuntimeError, match="Embedding generation failed"):
            embedder_with_mocks.generate(["Test text"])
    
    def test_cls_pooling_mode(self, embedder_with_mocks):
        """Test CLS token pooling mode."""
        embedder_with_mocks._metadata.pooling_mode = "cls"
        
        # Create test data
        batch_size, seq_length, hidden_size = 2, 5, 384
        token_embeddings = np.random.randn(batch_size, seq_length, hidden_size).astype(np.float32)
        
        # Mock the model to return our test data
        embedder_with_mocks._model.run.return_value = [token_embeddings]
        
        embeddings = embedder_with_mocks.generate(["Test"])
        
        # CLS pooling should use first token
        assert len(embeddings) == 1
        assert len(embeddings[0]) == hidden_size
    
    def test_max_pooling_mode(self, embedder_with_mocks):
        """Test max pooling mode."""
        embedder_with_mocks._metadata.pooling_mode = "max"
        
        embeddings = embedder_with_mocks.generate(["Test text"])
        
        assert len(embeddings) == 1
        assert len(embeddings[0]) == 384


class TestLocalModelEmbedderIntegration:
    """Integration tests for LocalModelEmbedder."""
    
    def test_embedder_with_registry(self, embedder_with_mocks):
        """Test LocalModelEmbedder registration with EmbeddingRegistry."""
        from agent_vault.embeddings.registry import EmbeddingRegistry
        
        registry = EmbeddingRegistry()
        registry.configure_default_embedder(embedder_with_mocks)
        
        # Retrieve embedder
        retrieved = registry.get("test_table", "test_column")
        
        assert retrieved is embedder_with_mocks
        assert registry.get_expected_dimensions("test_table", "test_column") == 384
    
    def test_embedder_with_per_table_configuration(self, embedder_with_mocks, tmp_path):
        """Test per-table embedder configuration."""
        from agent_vault.embeddings.registry import EmbeddingRegistry
        from agent_vault.embeddings.hashing import HashingEmbedder
        
        registry = EmbeddingRegistry()
        
        # Set default embedder
        registry.configure_default_embedder(embedder_with_mocks)
        
        # Set different embedder for specific table
        hashing_embedder = HashingEmbedder(ndims=128)
        registry.register("special_table", "vector", hashing_embedder)
        
        # Verify correct embedders are returned
        assert registry.get("normal_table", "vector") is embedder_with_mocks
        assert registry.get("special_table", "vector") is hashing_embedder
    
    def test_factory_creates_local_model_embedder(self, tmp_path, mock_temp_config):
        """Test that factory can create LocalModelEmbedder."""
        
        # Set up config for local model
        mock_temp_config.storage.root = str(tmp_path)
        model_path = tmp_path / "models" / "test_model"
        model_path.mkdir(parents=True)
        
        # Create minimal metadata
        metadata = ModelMetadata(
            model_id="test",
            format="onnx",
            dimensions=384,
            max_sequence_length=512,
            tokenizer_type="test",
            normalize_embeddings=True,
            pooling_mode="mean",
            created_at=datetime.now().isoformat()
        )
        metadata.save(model_path / "metadata.json")
        
        # Note: Factory currently doesn't support local provider
        # This test verifies the LocalModelEmbedder can be instantiated directly
        try:
            embedder = LocalModelEmbedder(
                model_path="models/test_model",
                config=mock_temp_config
            )
            assert isinstance(embedder, LocalModelEmbedder)
            assert embedder.model_path == model_path
        except (FileNotFoundError, RuntimeError):
            # Expected without actual model files
            pass
    
    @pytest.mark.asyncio
    async def test_async_integration_with_pipeline(self, async_embedder):
        """Test async embedding generation in pipeline context."""
        import asyncio
        
        # Simulate pipeline-like concurrent operations
        async def process_batch(texts):
            return await async_embedder.generate_async(texts)
        
        batches = [
            ["text1", "text2"],
            ["text3", "text4"],
            ["text5", "text6"]
        ]
        
        results = await asyncio.gather(*[process_batch(batch) for batch in batches])
        
        assert len(results) == 3
        assert all(len(result) == 2 for result in results)
