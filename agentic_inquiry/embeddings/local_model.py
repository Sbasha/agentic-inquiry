"""Local model embedder implementation.

This module provides support for locally-stored embedding models in ONNX and
safetensors formats, enabling offline operation without external API dependencies.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from agentic_inquiry.embeddings.base import Embedder

logger = logging.getLogger(__name__)


@dataclass
class ModelMetadata:
    """Metadata for a local embedding model.

    Attributes:
        model_id: Original HuggingFace ID or custom name
        format: Model format ("onnx", "safetensors", "pytorch")
        dimensions: Embedding dimensionality
        max_sequence_length: Maximum token sequence length
        tokenizer_type: Tokenizer class name
        normalize_embeddings: Whether model expects normalization
        pooling_mode: Pooling strategy ("mean", "cls", "max")
        created_at: ISO timestamp of model creation
        source_url: Original model URL (optional)
    """

    model_id: str
    format: str
    dimensions: int
    max_sequence_length: int
    tokenizer_type: str
    normalize_embeddings: bool
    pooling_mode: str
    created_at: str
    source_url: str | None = None

    def __post_init__(self) -> None:
        """Validate metadata fields after initialization."""
        self._validate()

    def _validate(self) -> None:
        """Validate metadata fields.

        Raises:
            ValueError: If any field is invalid
        """
        # Validate model_id
        if not self.model_id or not isinstance(self.model_id, str):
            raise ValueError("model_id must be a non-empty string")

        # Validate format
        valid_formats = {"onnx", "safetensors", "pytorch"}
        if self.format not in valid_formats:
            raise ValueError(
                f"format must be one of {valid_formats}, got '{self.format}'"
            )

        # Validate dimensions
        if not isinstance(self.dimensions, int) or self.dimensions <= 0:
            raise ValueError("dimensions must be a positive integer")

        # Validate max_sequence_length
        if (
            not isinstance(self.max_sequence_length, int)
            or self.max_sequence_length <= 0
        ):
            raise ValueError("max_sequence_length must be a positive integer")

        # Validate tokenizer_type
        if not self.tokenizer_type or not isinstance(self.tokenizer_type, str):
            raise ValueError("tokenizer_type must be a non-empty string")

        # Validate normalize_embeddings
        if not isinstance(self.normalize_embeddings, bool):
            raise ValueError("normalize_embeddings must be a boolean")

        # Validate pooling_mode
        valid_pooling_modes = {"mean", "cls", "max"}
        if self.pooling_mode not in valid_pooling_modes:
            raise ValueError(
                f"pooling_mode must be one of {valid_pooling_modes}, got '{self.pooling_mode}'"
            )

        # Validate created_at (basic check for non-empty string)
        if not self.created_at or not isinstance(self.created_at, str):
            raise ValueError("created_at must be a non-empty string")

        # Validate source_url (optional, but must be string if provided)
        if self.source_url is not None and not isinstance(self.source_url, str):
            raise ValueError("source_url must be a string or None")

    def save(self, path: Path) -> None:
        """Save metadata to JSON file.

        Args:
            path: Path to save metadata file

        Raises:
            OSError: If file cannot be written
        """
        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
        logger.info("Saved model metadata to %s", path)

    @classmethod
    def load(cls, path: Path) -> ModelMetadata:
        """Load metadata from JSON file.

        Args:
            path: Path to metadata file

        Returns:
            Loaded ModelMetadata instance

        Raises:
            FileNotFoundError: If metadata file doesn't exist
            ValueError: If metadata is invalid or missing required fields
            json.JSONDecodeError: If file contains invalid JSON
        """
        if not path.exists():
            raise FileNotFoundError(f"Metadata file not found: {path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in metadata file {path}: {e}") from e

        # Validate required fields are present
        required_fields = {
            "model_id",
            "format",
            "dimensions",
            "max_sequence_length",
            "tokenizer_type",
            "normalize_embeddings",
            "pooling_mode",
            "created_at",
        }
        missing_fields = required_fields - set(data.keys())
        if missing_fields:
            raise ValueError(f"Missing required fields in metadata: {missing_fields}")

        try:
            return cls(**data)
        except TypeError as e:
            raise ValueError(f"Invalid metadata structure: {e}") from e


class ModelLoader:
    """Helper class for loading local models.

    Handles model format detection, loading model weights, tokenizers,
    and metadata validation. Supports ONNX models with caching.
    """

    def __init__(self, workspace_root: Path):
        """Initialize model loader.

        Args:
            workspace_root: Root directory of the workspace
        """
        self.workspace_root = workspace_root
        self._model_cache: dict[Path, tuple[Any, Any, ModelMetadata]] = {}
        logger.debug("Initialized ModelLoader with workspace_root=%s", workspace_root)

    def detect_format(self, model_path: Path) -> str:
        """Detect model format from directory contents.

        Args:
            model_path: Path to model directory

        Returns:
            Model format: "onnx", "safetensors", or "pytorch"

        Raises:
            ValueError: If model format cannot be determined
            FileNotFoundError: If model_path doesn't exist
        """
        if not model_path.exists():
            raise FileNotFoundError(f"Model directory not found: {model_path}")

        if not model_path.is_dir():
            raise ValueError(f"Model path must be a directory: {model_path}")

        # Check for ONNX model
        if (model_path / "model.onnx").exists():
            logger.debug("Detected ONNX model format in %s", model_path)
            return "onnx"

        # Check for safetensors
        safetensors_files = list(model_path.glob("*.safetensors"))
        if safetensors_files:
            logger.debug("Detected safetensors model format in %s", model_path)
            return "safetensors"

        # Check for PyTorch
        if (model_path / "pytorch_model.bin").exists():
            logger.debug("Detected PyTorch model format in %s", model_path)
            return "pytorch"

        # No recognized format found
        raise ValueError(
            f"Could not detect model format in {model_path}. "
            "Expected model.onnx, *.safetensors, or pytorch_model.bin"
        )

    def _load_onnx_model(self, model_path: Path) -> ort.InferenceSession:
        """Load ONNX model using onnxruntime.

        Args:
            model_path: Path to model directory

        Returns:
            ONNX inference session

        Raises:
            FileNotFoundError: If model.onnx doesn't exist
            RuntimeError: If model loading fails
        """
        onnx_path = model_path / "model.onnx"

        if not onnx_path.exists():
            raise FileNotFoundError(f"ONNX model file not found: {onnx_path}")

        try:
            # Create inference session with CPU provider
            session_options = ort.SessionOptions()
            session_options.graph_optimization_level = (
                ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            )

            session = ort.InferenceSession(
                str(onnx_path),
                sess_options=session_options,
                providers=["CPUExecutionProvider"],
            )

            logger.debug(
                "Loaded ONNX model from %s with inputs: %s, outputs: %s",
                onnx_path,
                [inp.name for inp in session.get_inputs()],
                [out.name for out in session.get_outputs()],
            )

            return session

        except Exception as e:
            raise RuntimeError(
                f"Failed to load ONNX model from {onnx_path}: {e}"
            ) from e

    def _load_tokenizer(self, model_path: Path) -> Tokenizer:
        """Load tokenizer from tokenizer.json.

        Args:
            model_path: Path to model directory

        Returns:
            Loaded tokenizer

        Raises:
            FileNotFoundError: If tokenizer files are missing
            RuntimeError: If tokenizer loading fails
        """
        tokenizer_path = model_path / "tokenizer.json"

        if not tokenizer_path.exists():
            raise FileNotFoundError(
                f"Tokenizer file not found: {tokenizer_path}. "
                "Expected tokenizer.json in model directory."
            )

        try:
            tokenizer = Tokenizer.from_file(str(tokenizer_path))
            logger.debug("Loaded tokenizer from %s", tokenizer_path)

            # Load tokenizer config if available for additional settings
            config_path = model_path / "tokenizer_config.json"
            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        json.load(f)  # Load to validate file exists and is valid JSON
                    logger.debug("Loaded tokenizer config from %s", config_path)

                    # Apply any relevant config settings
                    # (tokenizers library handles most settings automatically)

                except Exception as e:
                    logger.warning(
                        "Failed to load tokenizer config from %s: %s", config_path, e
                    )

            return tokenizer

        except Exception as e:
            raise RuntimeError(
                f"Failed to load tokenizer from {tokenizer_path}: {e}"
            ) from e

    def load_model(self, model_path: Path) -> tuple[Any, Tokenizer, ModelMetadata]:
        """Load model, tokenizer, and metadata.

        Args:
            model_path: Path to model directory

        Returns:
            Tuple of (model, tokenizer, metadata)

        Raises:
            FileNotFoundError: If required files are missing
            ValueError: If model format is unsupported or metadata is invalid
            RuntimeError: If model or tokenizer loading fails
        """
        # Check cache first
        if model_path in self._model_cache:
            logger.debug("Using cached model from %s", model_path)
            return self._model_cache[model_path]

        logger.info("Loading model from %s", model_path)

        # Load metadata first
        metadata_path = model_path / "metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError(
                f"Metadata file not found: {metadata_path}. "
                "Model directory must contain metadata.json"
            )

        metadata = ModelMetadata.load(metadata_path)

        # Detect and validate format
        detected_format = self.detect_format(model_path)
        if detected_format != metadata.format:
            logger.warning(
                "Detected format '%s' differs from metadata format '%s'. "
                "Using detected format.",
                detected_format,
                metadata.format,
            )
            # Update metadata to match detected format
            metadata.format = detected_format

        # Load model based on format
        if metadata.format == "onnx":
            model = self._load_onnx_model(model_path)
        elif metadata.format == "safetensors":
            raise ValueError(
                "Safetensors format not yet supported. "
                "Please convert model to ONNX format."
            )
        elif metadata.format == "pytorch":
            raise ValueError(
                "PyTorch format not yet supported. Please convert model to ONNX format."
            )
        else:
            raise ValueError(
                f"Unsupported model format: {metadata.format}. Supported formats: onnx"
            )

        # Load tokenizer
        tokenizer = self._load_tokenizer(model_path)

        logger.info(
            "Successfully loaded %s model from %s (dimensions: %d)",
            metadata.format,
            model_path,
            metadata.dimensions,
        )

        # Cache the loaded model
        result = (model, tokenizer, metadata)
        self._model_cache[model_path] = result

        return result


class LocalModelEmbedder(Embedder):
    """Embedder implementation using locally-stored models.

    Supports ONNX and safetensors format models for offline embedding generation.
    Models are loaded from workspace-relative paths and cached in memory.
    """

    def __init__(
        self,
        model_path: str | Path,
        *,
        ndims: int | None = None,
        normalize: bool = True,
        batch_size: int = 32,
        config: Any | None = None,
    ):
        """Initialize local model embedder.

        Args:
            model_path: Path to model directory (workspace-relative or absolute)
            ndims: Expected embedding dimensions (auto-detected if None)
            normalize: Whether to normalize embeddings to unit length
            batch_size: Maximum batch size for inference
            config: Optional config instance
        """
        self.model_path = Path(model_path)
        self.normalize = normalize
        self.batch_size = batch_size
        self.config = config

        # Resolve workspace-relative paths
        if config and not self.model_path.is_absolute():
            workspace_root = Path(config.storage.root)
            self.model_path = workspace_root / self.model_path

        # Initialize loader (lazy loading)
        self._loader: ModelLoader | None = None
        self._model: Any | None = None
        self._tokenizer: Tokenizer | None = None
        self._metadata: ModelMetadata | None = None
        self._ndims = ndims

        # Thread pool for async operations
        self._executor: Any | None = None

        logger.info(
            "Initialized LocalModelEmbedder with model_path=%s, normalize=%s, batch_size=%d",
            self.model_path,
            normalize,
            batch_size,
        )

    def _ensure_loaded(self) -> None:
        """Ensure model is loaded (lazy loading).

        Raises:
            FileNotFoundError: If model files are missing
            ValueError: If model dimensions don't match expected dimensions
            RuntimeError: If model loading fails
        """
        if self._model is None:
            if self.config:
                workspace_root = Path(self.config.storage.root)
            else:
                workspace_root = Path.cwd()

            self._loader = ModelLoader(workspace_root)

            try:
                self._model, self._tokenizer, self._metadata = self._loader.load_model(
                    self.model_path
                )
            except FileNotFoundError as e:
                logger.error("Model files not found at %s", self.model_path)
                raise FileNotFoundError(
                    f"Model files not found at {self.model_path}. "
                    f"Run model conversion script to download and convert the model."
                ) from e
            except Exception as e:
                logger.error("Failed to load model from %s: %s", self.model_path, e)
                raise RuntimeError(f"Failed to load model: {e}") from e

            # Validate dimensions if specified
            if self._ndims is not None and self._metadata.dimensions != self._ndims:
                raise ValueError(
                    f"Model dimensions {self._metadata.dimensions} do not match "
                    f"expected dimensions {self._ndims}"
                )

            logger.info(
                "Model loaded successfully: %s (dimensions: %d, pooling: %s)",
                self._metadata.model_id,
                self._metadata.dimensions,
                self._metadata.pooling_mode,
            )

    def _tokenize_texts(self, texts: list[str]) -> dict[str, Any]:
        """Tokenize texts using the loaded tokenizer.

        Args:
            texts: List of text strings to tokenize

        Returns:
            Dictionary with input_ids and attention_mask tensors
        """
        if self._tokenizer is None:
            raise RuntimeError("Tokenizer not loaded")

        # Tokenize all texts
        encodings = self._tokenizer.encode_batch(texts)

        # Extract input_ids and attention_mask
        input_ids = [enc.ids for enc in encodings]
        attention_mask = [enc.attention_mask for enc in encodings]

        # Convert to numpy arrays with proper padding
        max_length = max(len(ids) for ids in input_ids)

        # Pad sequences
        padded_input_ids = np.zeros((len(texts), max_length), dtype=np.int64)
        padded_attention_mask = np.zeros((len(texts), max_length), dtype=np.int64)

        for i, (ids, mask) in enumerate(zip(input_ids, attention_mask)):
            padded_input_ids[i, : len(ids)] = ids
            padded_attention_mask[i, : len(mask)] = mask

        return {"input_ids": padded_input_ids, "attention_mask": padded_attention_mask}

    def _mean_pooling(self, token_embeddings: Any, attention_mask: Any) -> Any:
        """Apply mean pooling to token embeddings.

        Args:
            token_embeddings: Token-level embeddings from model
            attention_mask: Attention mask for valid tokens

        Returns:
            Pooled embeddings (one per text)
        """
        # Expand attention mask to match embedding dimensions
        # attention_mask shape: (batch_size, seq_length)
        # token_embeddings shape: (batch_size, seq_length, hidden_size)
        attention_mask_expanded = np.expand_dims(attention_mask, axis=-1)
        attention_mask_expanded = attention_mask_expanded.astype(np.float32)

        # Apply mask to embeddings
        masked_embeddings = token_embeddings * attention_mask_expanded

        # Sum embeddings
        sum_embeddings = np.sum(masked_embeddings, axis=1)

        # Sum attention mask to get count of valid tokens
        sum_mask = np.sum(attention_mask_expanded, axis=1)
        sum_mask = np.clip(sum_mask, a_min=1e-9, a_max=None)  # Avoid division by zero

        # Calculate mean
        mean_embeddings = sum_embeddings / sum_mask

        return mean_embeddings

    def _normalize_embeddings(self, embeddings: Any) -> Any:
        """Normalize embeddings to unit length.

        Args:
            embeddings: Embeddings to normalize

        Returns:
            Normalized embeddings
        """
        # Calculate L2 norm
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.clip(norms, a_min=1e-9, a_max=None)  # Avoid division by zero

        # Normalize
        normalized = embeddings / norms

        return normalized

    def _generate_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a single batch of texts.

        Args:
            texts: List of text strings (must not exceed batch_size)

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        # Tokenize texts
        inputs = self._tokenize_texts(texts)

        # Run inference
        if isinstance(self._model, ort.InferenceSession):
            # ONNX model inference
            input_names = [inp.name for inp in self._model.get_inputs()]
            output_names = [out.name for out in self._model.get_outputs()]

            # Prepare inputs for ONNX
            onnx_inputs = {}
            for name in input_names:
                if name == "input_ids":
                    onnx_inputs[name] = inputs["input_ids"]
                elif name == "attention_mask":
                    onnx_inputs[name] = inputs["attention_mask"]
                elif name == "token_type_ids":
                    # Some models require token_type_ids
                    onnx_inputs[name] = np.zeros_like(inputs["input_ids"])

            # Run inference
            outputs = self._model.run(output_names, onnx_inputs)

            # Get token embeddings (usually the first output)
            token_embeddings = outputs[0]
        else:
            raise ValueError(f"Unsupported model type: {type(self._model)}")

        # Apply pooling based on metadata
        if self._metadata and self._metadata.pooling_mode == "mean":
            embeddings = self._mean_pooling(token_embeddings, inputs["attention_mask"])
        elif self._metadata and self._metadata.pooling_mode == "cls":
            # Use CLS token (first token) embedding
            embeddings = token_embeddings[:, 0, :]
        elif self._metadata and self._metadata.pooling_mode == "max":
            # Max pooling
            embeddings = np.max(token_embeddings, axis=1)
        else:
            # Default to mean pooling
            logger.warning(
                "Unknown pooling mode '%s', using mean pooling",
                self._metadata.pooling_mode if self._metadata else "unknown",
            )
            embeddings = self._mean_pooling(token_embeddings, inputs["attention_mask"])

        # Normalize if configured
        if self.normalize:
            embeddings = self._normalize_embeddings(embeddings)

        # Convert to list of lists
        return embeddings.tolist()

    def generate(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for batch of texts.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors

        Raises:
            ValueError: If texts is empty or contains invalid inputs
            FileNotFoundError: If model files are missing
            RuntimeError: If embedding generation fails
        """
        if not texts:
            raise ValueError("Cannot generate embeddings for empty text list")

        # Validate inputs
        for i, text in enumerate(texts):
            if not isinstance(text, str):
                raise ValueError(f"Text at index {i} is not a string: {type(text)}")

        self._ensure_loaded()

        logger.debug("Generating embeddings for %d texts", len(texts))

        try:
            # Split into batches if necessary
            if len(texts) <= self.batch_size:
                return self._generate_batch(texts)

            # Process in batches
            all_embeddings = []
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i : i + self.batch_size]
                batch_embeddings = self._generate_batch(batch)
                all_embeddings.extend(batch_embeddings)

                logger.debug(
                    "Processed batch %d/%d (%d texts)",
                    i // self.batch_size + 1,
                    (len(texts) + self.batch_size - 1) // self.batch_size,
                    len(batch),
                )

            return all_embeddings

        except Exception as e:
            logger.error("Failed to generate embeddings: %s", e, exc_info=True)
            raise RuntimeError(f"Embedding generation failed: {e}") from e

    async def generate_async(self, texts: list[str]) -> list[list[float]]:
        """Async version of generate for non-blocking operation.

        Uses ThreadPoolExecutor to run the synchronous generate method
        in a separate thread, preventing blocking of the event loop.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors

        Raises:
            ValueError: If texts is empty or contains invalid inputs
            FileNotFoundError: If model files are missing
            RuntimeError: If embedding generation fails
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        # Initialize executor if needed
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1)

        # Run generate in thread pool
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self.generate, texts)

    def ndims(self) -> int:
        """Return embedding dimensionality.

        Returns:
            Number of dimensions in embedding vectors

        Raises:
            ValueError: If dimensions cannot be determined
        """
        if self._ndims is not None:
            return self._ndims

        self._ensure_loaded()

        if self._metadata:
            return self._metadata.dimensions

        raise ValueError("Could not determine embedding dimensions")

    def __del__(self) -> None:
        """Cleanup resources on deletion."""
        if self._executor is not None:
            try:
                self._executor.shutdown(wait=False)
            except Exception:
                pass  # Ignore errors during cleanup
