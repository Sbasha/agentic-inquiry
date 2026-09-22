# Hybrid Embedding Strategy

**Status:** Implemented
**Created:** 2026-01-08
**Updated:** 2026-01-08
**Related:** [embeddings.md](../api-reference/embeddings.md), [executors.py](../../agentic-inquiry/executors.py)

## Problem

The current embedding system uses a single heavyweight embedder (SentenceTransformer) for all data types:
- Document chunks (semantic text)
- Graph entities (code symbols)
- **Graph relationships** (simple type strings like "imports", "calls", "defines")

This creates performance bottlenecks:
1. Relationship types are simple strings - full ML inference is overkill
2. Thread pool starvation when semaphores allow more concurrent tasks than executor workers
3. Unnecessary GPU/CPU load for deterministic data

## Solution: Tiered Embedding Strategy

Use different embedders optimized for each data type:

| Data Type | Embedder | Rationale |
|-----------|----------|-----------|
| Document chunks | SentenceTransformer / ONNX / **Server-side (AlloyDB)** | Semantic similarity required |
| Graph entities | SentenceTransformer / ONNX / **Server-side (AlloyDB)** | Code symbol semantics matter |
| Graph relationships | **HashingEmbedder** | Deterministic, ~1000x faster |
| Tests | HashingEmbedder | No ML dependencies needed |

### Performance Comparison

| Embedder | Speed (texts/sec) | Quality | Dependencies | Use Case |
|----------|-------------------|---------|--------------|----------|
| SentenceTransformer | ~100 | High | torch, transformers | Local development |
| ONNX Local Model | ~300 | High | onnxruntime | Optimized local |
| **Server-side (AlloyDB)** | **~400 (fresh) / ~25 (incremental)** | High | AlloyDB, google_ml_integration | **Production GCP** |
| **HashingEmbedder** | ~100,000 | Low | None (pure Python) | Relationships only |

**Indexing Performance:**
- Local embedding: ~2-4 files/sec
- **Server-side (AlloyDB)**: **~16-19 files/sec** (27x faster than GENERATED ALWAYS AS approach)

## Implementation

### 1. Simple API: `configure_hybrid_embeddings()`

The `EmbeddingRegistry` provides a convenience method to configure hybrid embeddings:

```python
from agentic_inquiry.embeddings.registry import EmbeddingRegistry
from agentic_inquiry.embeddings.sentence_transformer import SentenceTransformerEmbedder

# Configure default for semantic content
registry = EmbeddingRegistry()
default_embedder = SentenceTransformerEmbedder(
    model_name="all-MiniLM-L6-v2",
    ndims=384
)
registry.configure_default_embedder(default_embedder, ndims=384)

# Enable hybrid embeddings - automatically registers HashingEmbedder for relationships
registry.configure_hybrid_embeddings()
```

### 2. Manual Registration (Alternative)

For more control, register embedders directly:

```python
from agentic_inquiry.embeddings.registry import embedding_registry
from agentic_inquiry.embeddings.hashing import HashingEmbedder

# Register fast embedder for relationships
relationship_embedder = HashingEmbedder(ndims=384)
embedding_registry.register(
    table_name="graph_relationships",
    column_name="vector",
    embedder=relationship_embedder,
    ndims=384
)
```

### 3. Configuration Schema (Future)

```yaml
embeddings:
  default_provider: sentence_transformer
  default_dimensions: 384

  # Provider-specific settings
  sentence_transformer:
    model_name: all-MiniLM-L6-v2
    ndims: 384

  hashing:
    ndims: 384
    ngram_size: 3

  # Per-table overrides (future enhancement)
  table_overrides:
    graph_relationships:
      provider: hashing  # Use fast hashing for relationship types
```

## Safety Considerations

### Dimension Safety

The `configure_hybrid_embeddings()` method requires explicit dimensions:

```python
# Option 1: Configure default embedder first (dimensions inherited)
registry.configure_default_embedder(embedder, ndims=384)
registry.configure_hybrid_embeddings()  # Uses 384 from default

# Option 2: Pass explicit dimensions
registry.configure_hybrid_embeddings(ndims=384)

# This raises StorageError - prevents dimension mismatches
registry = EmbeddingRegistry()
registry.configure_hybrid_embeddings()  # Error: no dimensions available
```

### Case Sensitivity

Relationship types should be normalized before embedding. The system uses consistent
lowercase relationship types: "imports", "calls", "defines", "inherits", etc.

### Migration Safety

For existing projects with data:
- Relationship vectors are primarily used for graph traversal, not semantic search
- The system uses type-based lookup, so vector format changes have minimal impact
- For full safety, re-index after enabling hybrid embeddings

## Benefits

1. **Performance**: ~1000x faster relationship embedding
2. **Resource Efficiency**: Fewer executor threads needed for relationships
3. **Consistency**: Relationship vectors are deterministic (same input = same output)
4. **Flexibility**: Easy to tune per use case

## Migration

### Phase 1: Relationship Embeddings (Implemented)
- `configure_hybrid_embeddings()` method added to `EmbeddingRegistry`
- Registers HashingEmbedder for `graph_relationships` table
- Relationship types are finite set - hashing is sufficient
- Tests added: `tests/embeddings/test_registry.py::TestHybridEmbeddings`

### Phase 2: Server-Side Embedding (Implemented)
- **NoOpEmbedder** added for server-side embedding strategies
- AlloyDB integration with `text-embedding-005` model (768 dimensions)
- `embedding_strategy` config option: "local" or "server_side"
- **Unified PostgreSQL provider** (`storage/providers/postgresql/`) supports both strategies via `BackendConfig`
- `validate_alloydb_config()` auto-configures server-side settings for AlloyDB backends
- Auto-embedding via `generate_embeddings()` method called automatically by pipeline after indexing
- Performance: 16+ files/sec indexing, ~400 chunks/sec embedding generation (fresh tables), ~25 chunks/sec (incremental)
- **Note:** Old `storage/providers/alloydb/` package is dead code (setup/CLI utilities still active, runtime providers unused)

### Phase 3: Configuration Support (Optional)
- Add `table_overrides` to EmbeddingsConfig
- Document in configuration guide

### Phase 4: ONNX Migration (Optional)
- Convert SentenceTransformer model to ONNX for 2-3x speedup
- Provide conversion script

## Server-Side Embedding Strategy

### Overview

Server-side embedding offloads embedding generation to the database, enabling significantly faster indexing for large codebases.

### Configuration

```yaml
storage:
  backend: "alloydb"
  embedding_strategy: "server_side"  # or "local"
  embedding_model: "text-embedding-005"  # AlloyDB model
  embedding_dim: 768  # Model dimensions

  # GCP settings
  gcp_project_id: "my-project"
  gcp_region: "us-central1"
  gcp_instance: "my-instance"
```

### Usage

```python
from agentic_inquiry.embeddings.noop import NoOpEmbedder
from agentic_inquiry.embeddings.registry import embedding_registry

# Configure NoOpEmbedder (no local computation)
embedder = NoOpEmbedder(ndims=768)
embedding_registry.configure_default_embedder(embedder, ndims=768)

# Pipeline skips local embedding, database generates them
await pipeline.index_directory(path="./src", wait=True)

# Embeddings generated automatically via:
# - PostgresVectorProvider.generate_embeddings()
# - PostgresGraphProvider.generate_embeddings()
```

### Performance Benefits

- **Indexing**: 16-19 files/sec average (vs 0.6-2 files/sec local, 27x improvement over GENERATED ALWAYS AS approach)
- **Embedding Generation** (automatic via pipeline):
  - **Fresh tables:** ~400 chunks/sec using `ai.initialize_embeddings()`
  - **Incremental:** ~25 chunks/sec using per-row `embedding()` function
- **Scale**: Production-tested on 16.7K files, 525K chunks, 269K entities
- **CPU**: Zero local compute required
- **Constraints**:
  - `ai.initialize_embeddings()` MUST run before ANY rows have embeddings (4MB Vertex AI limit)
  - Content truncation: `LEFT(content, 8000)` for fallback path (~2048 token model limit)
  - Batch size: ≤250 (Vertex AI instance limit)

### Implementation Details

**Unified PostgreSQL Provider** (`storage/providers/postgresql/`):
- `embedding_strategy` field on `BackendConfig` ("local" | "server_side")
- `validate_alloydb_config()` auto-sets server_side + text-embedding-005 + 768 dims for AlloyDB backend type
- Registry maps backend type `"alloydb"` → `PostgresVectorProvider` + `PostgresGraphProvider`
- Same provider code handles all PostgreSQL-compatible databases (PostgreSQL, CloudSQL, AlloyDB)
- **Old provider at `storage/providers/alloydb/`**: Dead code (runtime providers unused, setup/CLI utilities still active)

**Pipeline Integration** (automatic embedding generation):
- `_index_sync()` calls `provider.generate_embeddings()` after indexing for server-side backends
- Timeout handler also triggers auto-embed to ensure embeddings generated even on partial indexing
- NoOpEmbedder used in pipeline to skip local embedding computation
- **Performance**: Uses `ai.initialize_embeddings()` at ~400/sec for fresh tables, falls back to per-row `embedding()` at ~25/sec for incremental updates

**Provider Methods:**
- `upsert_chunks()` / `upsert_entities()` skip embedding column when server_side
- `generate_embeddings()` uses `ai.initialize_embeddings()` for fresh tables, per-row fallback otherwise
- `vector_search()` accepts string queries for server-side embedding
- `entity_vector_search()` accepts string queries for server-side embedding

**Key Files:**
- `storage/providers/postgresql/vector.py` - Vector provider with server-side support
- `storage/providers/postgresql/graph.py` - Graph provider with server-side support
- `storage/config.py` - `BackendConfig.embedding_strategy` field
- `storage/registry.py` - AlloyDB → PostgreSQL provider mapping
- `indexing/pipeline.py` - Auto-embed trigger after indexing

## Testing

```python
class TestHybridEmbeddings(unittest.TestCase):
    def test_configure_hybrid_embeddings_registers_hashing_for_relationships(self):
        """Test that configure_hybrid_embeddings registers HashingEmbedder."""
        registry = EmbeddingRegistry()
        registry.configure_default_embedder(SentenceTransformerEmbedder(ndims=384))
        registry.configure_hybrid_embeddings()

        embedder, dims = registry.get_configuration("graph_relationships", "vector")
        assert isinstance(embedder, HashingEmbedder)
        assert dims == 384

    def test_other_tables_still_use_default_embedder(self):
        """Test that non-relationship tables still use the default ML embedder."""
        registry = EmbeddingRegistry()
        default_embedder = SentenceTransformerEmbedder(ndims=384)
        registry.configure_default_embedder(default_embedder)
        registry.configure_hybrid_embeddings()

        # graph_relationships uses HashingEmbedder
        rel_embedder, _ = registry.get_configuration("graph_relationships", "vector")
        assert isinstance(rel_embedder, HashingEmbedder)

        # Other tables use default SentenceTransformer
        chunk_embedder, _ = registry.get_configuration("document_chunks", "vector")
        assert chunk_embedder is default_embedder
```

## Rollback

If issues arise, simply remove the `configure_hybrid_embeddings()` call - the system
falls back to the default embedder automatically.

## References

- `agentic_inquiry/embeddings/registry.py` - EmbeddingRegistry implementation
- `agentic_inquiry/embeddings/hashing.py` - HashingEmbedder implementation
- `agentic_inquiry/indexing/graph_builder.py` - Uses `get_embedder_configuration()`
- `tests/embeddings/test_registry.py::TestHybridEmbeddings` - Test suite
