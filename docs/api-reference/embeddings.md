---
title: "Embeddings API Reference"
tier: 3
audience: developer
journey: ["integration-developer", "advanced-user"]
related: ["../guides/local-models.md", "../guides/model-conversion.md", "../customization/extending.md"]
last_updated: 2025-10-29
---

# Embeddings API Reference

This document provides detailed API documentation for Agentic Inquiry's embedding system, including the LocalModelEmbedder, ModelLoader, and ModelMetadata classes.

## Overview

The embedding system provides a flexible architecture for generating vector embeddings from text. It supports multiple embedding providers through a common interface:

- **LocalModelEmbedder** - Uses locally-stored ONNX models
- **SentenceTransformerEmbedder** - Uses HuggingFace Sentence Transformers
- **FastEmbedEmbedder** - Uses qdrant/fastembed (ONNX Runtime)
- **HashingEmbedder** - Fast deterministic hashing
- **NoOpEmbedder** - Placeholder for a provider that embeds server-side
- **Custom embedders** - Implement your own

## LocalModelEmbedder

The `LocalModelEmbedder` class loads and uses locally-stored ONNX models for generating embeddings.

### Class Definition

```python
from agentic_inquiry.embeddings.local_model import LocalModelEmbedder

class LocalModelEmbedder(Embedder):
    """Embedder that uses locally-stored ONNX models."""
```

### Constructor

```python
def __init__(
    self,
    model_path: str | Path,
    *,
    ndims: int | None = None,
    normalize: bool = True,
    batch_size: int = 32,
    config: Config | None = None
) -> None:
    """Initialize local model embedder.
    
    Args:
        model_path: Path to model directory (workspace-relative or absolute).
                   Relative paths are resolved relative to storage root.
        ndims: Expected embedding dimensions. If None, auto-detected from
              model metadata. Used for validation.
        normalize: Whether to normalize embeddings to unit length.
                  Recommended for cosine similarity search.
        batch_size: Maximum batch size for inference. Larger batches are
                   faster but use more memory.
        config: Optional Config instance. If None, loads default config.
    
    Raises:
        ModelNotFoundError: If model directory or required files don't exist.
        ModelLoadError: If model fails to load.
        ValueError: If ndims doesn't match model dimensions.
    """
```

### Methods

#### generate()

```python
def generate(self, texts: List[str]) -> List[List[float]]:
    """Generate embeddings for a batch of texts.
    
    Args:
        texts: List of text strings to embed.
    
    Returns:
        List of embedding vectors, one per input text.
        Each vector is a list of floats with length equal to ndims().
    
    Raises:
        InferenceError: If embedding generation fails.
        ValueError: If texts is empty or contains invalid inputs.
    
    Example:
        >>> embedder = LocalModelEmbedder("models/all-MiniLM-L6-v2")
        >>> texts = ["function definition", "class implementation"]
        >>> embeddings = embedder.generate(texts)
        >>> len(embeddings)
        2
        >>> len(embeddings[0])
        384
    """
```

#### generate_async()

```python
async def generate_async(self, texts: List[str]) -> List[List[float]]:
    """Generate embeddings asynchronously.
    
    Uses ThreadPoolExecutor to run blocking inference in a separate thread,
    preventing blocking of the event loop.
    
    Args:
        texts: List of text strings to embed.
    
    Returns:
        List of embedding vectors, one per input text.
    
    Raises:
        InferenceError: If embedding generation fails.
        ValueError: If texts is empty or contains invalid inputs.
    
    Example:
        >>> embedder = LocalModelEmbedder("models/all-MiniLM-L6-v2")
        >>> embeddings = await embedder.generate_async(["query text"])
    """
```

#### ndims()

```python
def ndims(self) -> int:
    """Return the dimensionality of embedding vectors.
    
    Returns:
        Number of dimensions in each embedding vector.
    
    Example:
        >>> embedder = LocalModelEmbedder("models/all-MiniLM-L6-v2")
        >>> embedder.ndims()
        384
    """
```

### Usage Examples

#### Basic Usage

```python
from agentic_inquiry.embeddings.local_model import LocalModelEmbedder
from agentic_inquiry.config import Config

# Create embedder
config = Config.load()
embedder = LocalModelEmbedder(
    model_path="models/all-MiniLM-L6-v2",
    config=config
)

# Generate embeddings
texts = ["function definition", "class implementation"]
embeddings = embedder.generate(texts)

print(f"Generated {len(embeddings)} embeddings")
print(f"Dimensions: {embedder.ndims()}")
```

#### With Custom Settings

```python
from agentic_inquiry.embeddings.local_model import LocalModelEmbedder

# Custom configuration
embedder = LocalModelEmbedder(
    model_path="models/all-mpnet-base-v2",
    normalize=True,      # Normalize to unit length
    batch_size=16,       # Smaller batches for large model
    ndims=768           # Validate dimensions
)

# Generate embeddings
embeddings = embedder.generate(["sample text"])
```

#### Async Usage

```python
from agentic_inquiry.embeddings.local_model import LocalModelEmbedder

embedder = LocalModelEmbedder("models/all-MiniLM-L6-v2")

# Async embedding generation
async def embed_texts():
    texts = ["query 1", "query 2", "query 3"]
    embeddings = await embedder.generate_async(texts)
    return embeddings

# Use in async context
embeddings = await embed_texts()
```

#### With EmbeddingRegistry

```python
from agentic_inquiry.embeddings.local_model import LocalModelEmbedder
from agentic_inquiry.embeddings.registry import embedding_registry

# Create and register embedder
embedder = LocalModelEmbedder("models/all-MiniLM-L6-v2")
embedding_registry.configure_default_embedder(embedder, ndims=384)

# Now used automatically by all components
from agentic_inquiry.config import Config
from agentic_inquiry.storage.facade import StorageFacade
from agentic_inquiry.indexing.pipeline import IndexingPipeline
config = Config.load()
storage = await StorageFacade.from_config(config, project_id="my-project")
pipeline = IndexingPipeline(db_manager=storage, config=config, project_id="my-project")
```

## ModelLoader

The `ModelLoader` class handles loading ONNX models, tokenizers, and metadata.

### Class Definition

```python
from agentic_inquiry.embeddings.local_model import ModelLoader

class ModelLoader:
    """Loads and caches ONNX models and tokenizers."""
```

### Constructor

```python
def __init__(self, workspace_root: Path) -> None:
    """Initialize model loader.
    
    Args:
        workspace_root: Root directory for resolving relative model paths.
    """
```

### Methods

#### load_model()

```python
def load_model(
    self,
    model_path: Path
) -> Tuple[InferenceSession, Tokenizer, ModelMetadata]:
    """Load model, tokenizer, and metadata.
    
    Args:
        model_path: Path to model directory.
    
    Returns:
        Tuple of (onnx_session, tokenizer, metadata).
    
    Raises:
        ModelNotFoundError: If model files don't exist.
        ModelLoadError: If loading fails.
        UnsupportedModelFormatError: If model format is not supported.
    
    Example:
        >>> loader = ModelLoader(Path(".agentic-inquiry"))
        >>> session, tokenizer, metadata = loader.load_model(
        ...     Path("models/all-MiniLM-L6-v2")
        ... )
        >>> print(f"Dimensions: {metadata.dimensions}")
    """
```

#### detect_format()

```python
def detect_format(self, model_path: Path) -> str:
    """Detect model format from directory contents.
    
    Args:
        model_path: Path to model directory.
    
    Returns:
        Format string: "onnx", "safetensors", or "pytorch".
    
    Raises:
        UnsupportedModelFormatError: If format cannot be determined.
    
    Example:
        >>> loader = ModelLoader(Path(".agentic-inquiry"))
        >>> format = loader.detect_format(Path("models/my-model"))
        >>> print(format)
        'onnx'
    """
```

### Usage Examples

#### Loading a Model

```python
from pathlib import Path
from agentic_inquiry.embeddings.local_model import ModelLoader

# Create loader
loader = ModelLoader(workspace_root=Path(".agentic-inquiry"))

# Load model
model_path = Path("models/all-MiniLM-L6-v2")
session, tokenizer, metadata = loader.load_model(model_path)

print(f"Model format: {metadata.format}")
print(f"Dimensions: {metadata.dimensions}")
print(f"Max sequence length: {metadata.max_sequence_length}")
```

#### Detecting Format

```python
from pathlib import Path
from agentic_inquiry.embeddings.local_model import ModelLoader

loader = ModelLoader(workspace_root=Path(".agentic-inquiry"))

# Detect format
format = loader.detect_format(Path("models/my-model"))
print(f"Detected format: {format}")
```

## ModelMetadata

The `ModelMetadata` class stores metadata about converted models.

### Class Definition

```python
from agentic_inquiry.embeddings.local_model import ModelMetadata
from dataclasses import dataclass

@dataclass
class ModelMetadata:
    """Metadata for a local embedding model."""
    
    model_id: str                    # Original HuggingFace ID or custom name
    format: str                      # "onnx", "safetensors", "pytorch"
    dimensions: int                  # Embedding dimensionality
    max_sequence_length: int         # Maximum token sequence length
    tokenizer_type: str              # Tokenizer class name
    normalize_embeddings: bool       # Whether model expects normalization
    pooling_mode: str                # "mean", "cls", "max"
    created_at: str                  # ISO timestamp
    source_url: str | None           # Original model URL
```

### Methods

#### save()

```python
def save(self, path: Path) -> None:
    """Save metadata to JSON file.
    
    Args:
        path: Path to save metadata.json file.
    
    Example:
        >>> metadata = ModelMetadata(
        ...     model_id="all-MiniLM-L6-v2",
        ...     format="onnx",
        ...     dimensions=384,
        ...     max_sequence_length=512,
        ...     tokenizer_type="BertTokenizer",
        ...     normalize_embeddings=True,
        ...     pooling_mode="mean",
        ...     created_at="2025-10-29T12:00:00Z",
        ...     source_url="https://huggingface.co/..."
        ... )
        >>> metadata.save(Path("models/my-model/metadata.json"))
    """
```

#### load()

```python
@classmethod
def load(cls, path: Path) -> "ModelMetadata":
    """Load metadata from JSON file.
    
    Args:
        path: Path to metadata.json file.
    
    Returns:
        ModelMetadata instance.
    
    Raises:
        FileNotFoundError: If metadata file doesn't exist.
        ValueError: If metadata is invalid.
    
    Example:
        >>> metadata = ModelMetadata.load(
        ...     Path("models/my-model/metadata.json")
        ... )
        >>> print(f"Dimensions: {metadata.dimensions}")
    """
```

### Usage Examples

#### Creating and Saving Metadata

```python
from pathlib import Path
from datetime import datetime
from agentic_inquiry.embeddings.local_model import ModelMetadata

# Create metadata
metadata = ModelMetadata(
    model_id="sentence-transformers/all-MiniLM-L6-v2",
    format="onnx",
    dimensions=384,
    max_sequence_length=512,
    tokenizer_type="BertTokenizer",
    normalize_embeddings=True,
    pooling_mode="mean",
    created_at=datetime.utcnow().isoformat() + "Z",
    source_url="https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2"
)

# Save to file
metadata.save(Path("models/all-MiniLM-L6-v2/metadata.json"))
```

#### Loading Metadata

```python
from pathlib import Path
from agentic_inquiry.embeddings.local_model import ModelMetadata

# Load metadata
metadata = ModelMetadata.load(
    Path("models/all-MiniLM-L6-v2/metadata.json")
)

# Access fields
print(f"Model: {metadata.model_id}")
print(f"Dimensions: {metadata.dimensions}")
print(f"Format: {metadata.format}")
print(f"Pooling: {metadata.pooling_mode}")
```

## Configuration Schema

### Local Model Configuration

```yaml
embeddings:
  provider: "local"
  local_model:
    model_path: "models/all-MiniLM-L6-v2"  # Required
    normalize: true                         # Optional, default: true
    batch_size: 32                          # Optional, default: 32
```

### Configuration Fields

#### `embeddings.provider`

**Type:** `string`  
**Required:** Yes  
**Values:** `"local"`, `"sentence_transformer"`, `"hashing"`  
**Default:** `"sentence_transformer"`

Specifies which embedding provider to use.

#### `embeddings.local_model.model_path`

**Type:** `string`  
**Required:** Yes (when provider is "local")  
**Default:** None

Path to model directory, relative to `storage.root` or absolute.

**Examples:**
```yaml
# Relative to storage root
model_path: "models/all-MiniLM-L6-v2"

# Absolute path
model_path: "/var/lib/models/all-MiniLM-L6-v2"
```

#### `embeddings.local_model.normalize`

**Type:** `boolean`  
**Required:** No  
**Default:** `true`

Whether to normalize embeddings to unit length. Recommended for cosine similarity search.

#### `embeddings.local_model.batch_size`

**Type:** `integer`  
**Required:** No  
**Default:** `32`  
**Range:** 1-1024

Maximum number of texts to process in a single inference call. Larger values are faster but use more memory.

### Environment Variables

Override configuration with environment variables:

| Variable | Type | Description |
|----------|------|-------------|
| `INQUIRY_EMBEDDINGS_PROVIDER` | string | Embedding provider type |
| `INQUIRY_EMBEDDINGS_LOCAL_MODEL_PATH` | string | Path to model directory |
| `INQUIRY_EMBEDDINGS_LOCAL_NORMALIZE` | boolean | Enable normalization |
| `INQUIRY_EMBEDDINGS_LOCAL_BATCH_SIZE` | integer | Batch size for inference |

**Example:**
```bash
export INQUIRY_EMBEDDINGS_PROVIDER=local
export INQUIRY_EMBEDDINGS_LOCAL_MODEL_PATH=models/all-MiniLM-L6-v2
export INQUIRY_EMBEDDINGS_LOCAL_NORMALIZE=true
export INQUIRY_EMBEDDINGS_LOCAL_BATCH_SIZE=64
```

## Exceptions

### ModelNotFoundError

Raised when model directory or required files don't exist.

```python
from agentic_inquiry.embeddings.local_model import ModelNotFoundError

try:
    embedder = LocalModelEmbedder("models/nonexistent")
except ModelNotFoundError as e:
    print(f"Model not found: {e}")
```

### ModelLoadError

Raised when model fails to load.

```python
from agentic_inquiry.embeddings.local_model import ModelLoadError

try:
    embedder = LocalModelEmbedder("models/corrupted")
except ModelLoadError as e:
    print(f"Failed to load model: {e}")
```

### UnsupportedModelFormatError

Raised when model format is not supported.

```python
from agentic_inquiry.embeddings.local_model import UnsupportedModelFormatError

try:
    loader = ModelLoader(Path(".agentic-inquiry"))
    loader.detect_format(Path("models/unsupported"))
except UnsupportedModelFormatError as e:
    print(f"Unsupported format: {e}")
```

### InferenceError

Raised when embedding generation fails.

```python
from agentic_inquiry.embeddings.local_model import InferenceError

try:
    embeddings = embedder.generate(["text"])
except InferenceError as e:
    print(f"Inference failed: {e}")
```

## Type Hints

### Common Types

```python
from typing import List, Tuple
from pathlib import Path
from onnxruntime import InferenceSession
from tokenizers import Tokenizer

# Embedding vector
Embedding = List[float]

# Batch of embeddings
Embeddings = List[Embedding]

# Model loading result
ModelLoadResult = Tuple[InferenceSession, Tokenizer, ModelMetadata]
```

## Best Practices

### Error Handling

Always handle potential errors:

```python
from agentic_inquiry.embeddings.local_model import (
    LocalModelEmbedder,
    ModelNotFoundError,
    InferenceError
)

try:
    embedder = LocalModelEmbedder("models/my-model")
    embeddings = embedder.generate(["text"])
except ModelNotFoundError:
    print("Model not found. Run: uv run python scripts/convert_model.py <model-id>")
except InferenceError as e:
    print(f"Inference failed: {e}")
```

### Resource Management

Models are cached automatically, but you can control memory usage:

```python
# Use smaller batch sizes for large models
embedder = LocalModelEmbedder(
    model_path="models/large-model",
    batch_size=16  # Reduce memory usage
)

# Process in chunks for very large datasets
def embed_large_dataset(texts: List[str], chunk_size: int = 1000):
    embedder = LocalModelEmbedder("models/my-model")
    all_embeddings = []
    
    for i in range(0, len(texts), chunk_size):
        chunk = texts[i:i + chunk_size]
        embeddings = embedder.generate(chunk)
        all_embeddings.extend(embeddings)
    
    return all_embeddings
```

### Performance Optimization

```python
# Tune batch size for your hardware
embedder = LocalModelEmbedder(
    model_path="models/my-model",
    batch_size=64  # Increase for better throughput
)

# Use async for concurrent operations
async def embed_multiple_queries(queries: List[str]):
    embedder = LocalModelEmbedder("models/my-model")
    tasks = [embedder.generate_async([q]) for q in queries]
    results = await asyncio.gather(*tasks)
    return [r[0] for r in results]
```

## NoOpEmbedder

`agentic_inquiry.embeddings.noop.NoOpEmbedder` satisfies the `Embedder` interface without loading a model and returns zero vectors. The embeddings factory configures it when the provider's `ProviderCapabilities` or the backend's `embedding_strategy` setting is `server_side`. No shipped provider embeds server-side, so setting `embedding_strategy: server_side` on a shipped backend makes indexing store zero vectors. The server-side seam is described under "Embedding placement" in [storage-backends.md](../storage-backends.md).

## Environment Variables

Override configuration with environment variables:

| Variable | Type | Description |
|----------|------|-------------|
| `INQUIRY_EMBEDDINGS_PROVIDER` | string | Embedding provider type |
| `INQUIRY_EMBEDDINGS_LOCAL_MODEL_PATH` | string | Path to model directory |
| `INQUIRY_EMBEDDINGS_LOCAL_NORMALIZE` | boolean | Enable normalization |
| `INQUIRY_EMBEDDINGS_LOCAL_BATCH_SIZE` | integer | Batch size for inference |

**Example:**
```bash
# Local embedding
export INQUIRY_EMBEDDINGS_PROVIDER=local
export INQUIRY_EMBEDDINGS_LOCAL_MODEL_PATH=models/all-MiniLM-L6-v2
```

## See Also

- [Custom Embeddings](../customization/extending.md#custom-embeddings) - Creating custom embedders
- [Hybrid Embedding Strategy](../design/hybrid-embedding-strategy.md) - Design document
