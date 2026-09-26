---
title: "Extending Agentic Inquiry"
tier: 3
audience: developer
journey: ["extension-developer"]
related: ["../architecture/design-decisions.md", "../api-reference/api.md"]
last_updated: 2026-02-16
---

# Extending Agentic Inquiry

> Historical reference. This page describes PostgreSQL-family providers, cloud connectors or remote embedders that are not part of this local-only distribution. It is retained as design input for the external provider contract in [storage-backends.md](../storage-backends.md).

## Overview

Agentic Inquiry is designed to be extensible at multiple levels. You can customize parsers to handle new file formats, implement custom embedding models for domain-specific search, tune search behavior for your use case, and even integrate alternative storage backends.

This guide covers all extension points with consistent patterns and examples.

## Extension Points

Agentic Inquiry provides four primary extension points:

1. **Custom Parsers** - Handle specialized file formats or extraction strategies
2. **Custom Embeddings** - Use domain-specific or external embedding models
3. **Search Tuning** - Optimize search behavior and ranking
4. **Storage Backends** - Integrate alternative database systems

## Plugin System

**Primary Interface**: Users interact with Agentic Inquiry through Claude Code plugin skills, not direct API calls.

Plugin skills (installed via `.claude/settings.json`):
- `/ai:search <query>` - Semantic search across code and docs
- `/ai:index <path>` - Index a codebase
- `/ai:onboard <path>` - AI-powered codebase onboarding
- `/ai:entity <name>` - Understand a code entity
- `/ai:impact <symbol>` - Analyze change impact
- `/ai:lineage <symbol>` - Trace data flow
- `/ai:memory` - Save/recall project insights
- `/ai:setup` - Configure storage backend
- `/ai:env` - Manage environments
- `/ai:status` - Show project state

Developer skills: `/ai-dev:coding-guidelines`, `/ai-dev:testing`, `/ai-dev:quality`, `/ai-dev:review`, `/ai-dev:commit`

Plugins are located in `extensions/claude/ai/` and `extensions/claude/ai-dev/`. The CLI (`ai` command) is available for scripting and automation, but plugin skills are the recommended interface for interactive use. Repo-local `.github/` and `.codex/` mirrors point back to the same canonical Claude tree for Copilot and Codex installs.

## Custom Parsers

### Overview

Create custom parsers to handle specialized file formats, extract domain-specific information, or implement alternative parsing strategies.

**Use cases:**
- Parse proprietary or domain-specific file formats
- Extract specialized metadata from standard formats
- Implement alternative parsing strategies (e.g., regex-based vs. tree-sitter)
- Add support for new programming languages
- Extract custom document entities (e.g., legal citations, scientific references)

### Parser Interface

Parsers follow a simple protocol:

```python
from agentic_inquiry.parsers.models import ParsedDocument

class MyParser:
    def can_parse(self, path: str) -> bool:
        """Check if this parser can handle the file (optional but recommended)."""
        return path.endswith('.myformat')
    
    def parse(self, path: str) -> ParsedDocument:
        """Parse the file and return structured document."""
        # Your parsing logic here
        pass
```

### Quick Example

Minimal custom parser for CSV files:

```python
import csv
from pathlib import Path
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk

class CSVParser:
    """Parse CSV files into structured chunks."""
    
    def can_parse(self, path: str) -> bool:
        return path.endswith('.csv')
    
    def parse(self, path: str) -> ParsedDocument:
        file_path = Path(path)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        # Create one chunk per row
        chunks = []
        for idx, row in enumerate(rows):
            content = ', '.join(f"{k}: {v}" for k, v in row.items())
            chunk = ParserChunk(
                content=content,
                fts_text=content,
                content_type="CSV_ROW",
                line_start=idx + 2,
                line_end=idx + 2,
                element_type="row",
                element_name=f"row_{idx}",
                metadata={"row_index": idx},
            )
            chunks.append(chunk)
        
        return ParsedDocument(
            doc_id=str(file_path.resolve()),
            file_path=str(file_path),
            chunks=chunks,
            metadata={"row_count": len(rows)},
        )
```

### Parser Data Models

**ParsedDocument**: Container for the entire parsed file
- `doc_id`: Unique identifier (typically absolute file path)
- `file_path`: Path to the source file
- `chunks`: List of ParserChunk objects
- `metadata`: Optional document-level metadata

**ParserChunk**: Represents a semantic unit of content
- `content`: The actual text content
- `fts_text`: Text optimized for full-text search (optional)
- `content_type`: Type of content (e.g., "CODE", "PROSE", "TABLE")
- `language`: Programming language or natural language
- `element_type`: Type of element (e.g., "function", "heading", "paragraph")
- `element_name`: Name of the element
- `symbols`: List of code symbols (for code parsers)
- `relationships`: List of ParserRelationship objects
- `line_start`, `line_end`: Line numbers in source file
- `metadata`: Additional JSON-serializable metadata
- `ranking_signals`: Metrics for search ranking

### Metadata Guidelines

`metadata` is stored as a single JSON string, so any JSON-serializable values
work, including lists and nested dicts. If one value cannot be encoded (a
`Path`, a `datetime`), the whole dict is replaced with `{}` and a warning is
logged; convert such values to strings first.

```python
chunk = ParserChunk(
    content="...",
    symbols=["parse_row"],                 # Top-level field: searchable
    metadata={
        "tags": ["tag1", "tag2"],
        "source": {"sheet": "Q3", "row": 12},
    },
    ranking_signals={
        "importance": 0.8,
        "complexity": 0.5,
    }
)
```

- Prefer top-level fields (`symbols`, `language`, etc.) for data you want to
  search or filter on; `metadata` is returned with the chunk but not indexed
- Use `ranking_signals` for metrics and scores

### Registering Parsers

Use the `@register_parser` decorator:

```python
from agentic_inquiry.parsers.executor import register_parser

@register_parser("csv")
class CSVParser:
    def can_parse(self, path: str) -> bool:
        return path.endswith('.csv')
    
    def parse(self, path: str) -> ParsedDocument:
        # Implementation
        pass
```

Then use in parser chains:

```python
from agentic_inquiry.parsers.chain import ParserChain

chain = ParserChain(["csv", "unified_code", "fallback_text"])
doc = chain.parse("data.csv")
```

### Parser Best Practices

1. **Implement can_parse**: Enables efficient parser selection
2. **Use semantic chunking**: Create chunks that represent meaningful units
3. **Generate good FTS text**: Include searchable keywords and context
4. **Extract relationships**: Enable graph-based navigation
5. **Follow metadata guidelines**: Avoid lists and nested dicts
6. **Handle errors gracefully**: Return partial results when possible
7. **Add ranking signals**: Help search prioritize important content
8. **Test thoroughly**: Cover normal cases, edge cases, and errors

## Custom Embeddings

### Overview

Implement custom embedders to use specialized models, integrate with external services, or optimize for your specific domain.

**Use cases:**
- Use domain-specific embedding models (CodeBERT, BioBERT, etc.)
- Integrate with external embedding services (OpenAI, Cohere, etc.)
- Implement custom embedding strategies (weighted combinations)
- Use multilingual or cross-lingual embeddings
- Optimize embeddings for specific search tasks

### Embedder Interface

All embedders must implement the `Embedder` abstract base class:

```python
from agentic_inquiry.embeddings.base import Embedder
from typing import List

class MyEmbedder(Embedder):
    def generate(self, texts: List[str]) -> List[List[float]]:
        """Generate vector embeddings for a batch of texts."""
        pass
    
    def ndims(self) -> int:
        """Return the dimensionality of the embedding vector."""
        pass
```

### Quick Example

Simple custom embedder using OpenAI's API:

```python
from agentic_inquiry.embeddings.base import Embedder
from typing import List
import openai
import os

class OpenAIEmbedder(Embedder):
    """Embedder using OpenAI's embedding API."""
    
    def __init__(self, model: str = "text-embedding-ada-002", api_key: str = None):
        self.model = model
        self._ndims = 1536  # Ada-002 dimensions
        openai.api_key = api_key or os.getenv("OPENAI_API_KEY")
    
    def generate(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using OpenAI API."""
        response = openai.Embedding.create(
            input=texts,
            model=self.model
        )
        return [item['embedding'] for item in response['data']]
    
    def ndims(self) -> int:
        """Return embedding dimensionality."""
        return self._ndims
```

### Embedder Implementation Template

Basic template for custom embedders:

```python
from agentic_inquiry.embeddings.base import Embedder
from typing import List
import logging

logger = logging.getLogger(__name__)

class CustomEmbedder(Embedder):
    """Custom embedder implementation."""
    
    def __init__(self, model_name: str = "default", ndims: int = 384):
        self.model_name = model_name
        self._ndims = ndims
        self._model = self._load_model()
    
    def _load_model(self):
        """Load the embedding model."""
        logger.info(f"Loading embedding model: {self.model_name}")
        # Your model loading logic here
        return None
    
    def generate(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a batch of texts."""
        if not texts:
            return []
        
        # Validate inputs
        for text in texts:
            if not isinstance(text, str):
                raise ValueError("All inputs must be strings")
        
        # Generate embeddings
        embeddings = []
        for text in texts:
            vector = self._embed_single(text)
            embeddings.append(vector)
        
        return embeddings
    
    def _embed_single(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        # Your embedding logic here
        return [0.0] * self._ndims
    
    def ndims(self) -> int:
        """Return embedding dimensionality."""
        return self._ndims
```

### Registering Embedders

Register your embedder with the global registry:

```python
from agentic_inquiry.embeddings.registry import embedding_registry

# Create your embedder
my_embedder = CustomEmbedder(model_name="my-model", ndims=768)

# Register as default
embedding_registry.configure_default_embedder(my_embedder, ndims=768)

# Or register for specific table/column
embedding_registry.register(
    table_name="document_chunks",
    column_name="vector",
    embedder=my_embedder,
    ndims=768
)
```

### Batch Processing

Optimize for large batches:

```python
class BatchedEmbedder(Embedder):
    """Embedder with efficient batch processing."""
    
    def __init__(self, model_name: str, batch_size: int = 32):
        self.model_name = model_name
        self.batch_size = batch_size
        self._ndims = 384
        self._model = self._load_model()
    
    def generate(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings with batching."""
        all_embeddings = []
        
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            batch_embeddings = self._generate_batch(batch)
            all_embeddings.extend(batch_embeddings)
        
        return all_embeddings
    
    def _generate_batch(self, batch: List[str]) -> List[List[float]]:
        """Generate embeddings for a single batch."""
        # Your batched inference logic
        return [[0.0] * self._ndims for _ in batch]
    
    def ndims(self) -> int:
        return self._ndims
```

### Embedder Best Practices

1. **Validate inputs**: Check that all inputs are strings
2. **Handle errors gracefully**: Provide fallbacks or meaningful errors
3. **Optimize batching**: Process multiple texts efficiently
4. **Cache when appropriate**: Avoid recomputing identical embeddings
5. **Normalize vectors**: Consider L2 normalization for cosine similarity
6. **Document dimensions**: Clearly specify embedding dimensionality
7. **Test thoroughly**: Verify correctness, consistency, and performance
8. **Consider memory**: Large models may require GPU or memory management

## Search Tuning

### Overview

Agentic Inquiry provides hybrid search combining vector similarity and full-text search with graph-aware ranking. Tune search behavior for optimal results in your specific use case.

**Use cases:**
- Optimize search relevance for your domain
- Balance precision vs. recall
- Tune ranking for code vs. documentation
- Adjust graph influence on results
- Configure search limits and filters
- Customize result scoring

### Quick Configuration

Basic search tuning via configuration:

```yaml
# agentic-inquiry.yaml
search:
  default_limit: 10
  max_limit: 100
  
  hybrid_search:
    vector_weight: 0.7      # Weight for vector similarity
    fts_weight: 0.3         # Weight for full-text search
    rerank_by_graph: true   # Use graph metadata for ranking
  
  graph_search:
    max_depth: 3            # Maximum graph traversal depth
    relationship_types:     # Relationship types to follow
      - calls
      - imports
      - contains
      - references
```

### Vector vs. Full-Text Balance

Adjust the balance between semantic and keyword matching:

**Tuning guidelines:**

- **High vector weight (0.7-0.9)**: Better for semantic/conceptual queries
  - Example: "error handling patterns", "authentication logic"
  - Use when: Users search by concept rather than exact terms

- **High FTS weight (0.7-0.9)**: Better for exact term matching
  - Example: "UserRepository", "calculate_total"
  - Use when: Users search for specific names or identifiers

- **Balanced (0.5/0.5)**: Good general-purpose default
  - Works well for mixed queries
  - Provides both semantic and exact matching

### Graph-Aware Ranking

Graph reranking uses PageRank-style metrics to boost important entities:

```yaml
search:
  hybrid_search:
    rerank_by_graph: true  # Enable graph reranking
```

**When to use:**
- Code search: Boost frequently-called functions
- Documentation: Boost central concepts
- API search: Boost core interfaces

**When to disable:**
- Simple keyword search
- When graph data is sparse
- When recency matters more than importance

### Filtering and Scoping

Filter results by metadata:

```python
from agentic_inquiry.search.service import SearchService

# Filter by file type
results = await search_service.hybrid_search(
    query_vector=embedding,
    query_fts="authentication",
    filters={"language": "python"},
    limit=10,
)

# Filter by multiple criteria
results = await search_service.hybrid_search(
    query_vector=embedding,
    query_fts="error handling",
    filters={
        "language": "python",
        "content_type": "CODE",
    },
    limit=10,
)
```

### Result Limits

Configure limits for different use cases:

```yaml
search:
  default_limit: 10   # Default number of results
  max_limit: 100      # Maximum allowed results
```

**Tuning guidelines:**

- **Small limits (5-10)**: Fast, focused results for interactive search
- **Medium limits (20-50)**: Balanced coverage for general search
- **Large limits (100+)**: Comprehensive results for batch processing

### Common Tuning Scenarios

**Code Search** - Optimize for finding code by function/class names:
```yaml
search:
  hybrid_search:
    vector_weight: 0.3
    fts_weight: 0.7
    rerank_by_graph: true
```

**Documentation Search** - Optimize for conceptual/semantic search:
```yaml
search:
  hybrid_search:
    vector_weight: 0.8
    fts_weight: 0.2
    rerank_by_graph: false
```

**API Discovery** - Find related APIs and their usage:
```yaml
search:
  hybrid_search:
    vector_weight: 0.6
    fts_weight: 0.4
    rerank_by_graph: true
  graph_search:
    max_depth: 2
    relationship_types:
      - calls
      - imports
```

### Search Best Practices

1. **Start with defaults**: Use default configuration as baseline
2. **Measure before tuning**: Establish baseline metrics
3. **Tune incrementally**: Change one parameter at a time
4. **Test with real queries**: Use actual user queries for evaluation
5. **Consider your domain**: Code search differs from document search
6. **Balance speed vs. quality**: More comprehensive search is slower
7. **Monitor performance**: Track search latency and quality over time
8. **Use appropriate limits**: Don't fetch more results than needed
9. **Leverage graph data**: Graph reranking improves relevance

## Storage Backends

### Overview

Agentic Inquiry supports multiple storage backends for different deployment scenarios. Choose based on your requirements for scale, infrastructure, and embedding strategy.

**Use cases:**
- Local development with embedded database (LanceDB)
- Self-hosted production with PostgreSQL
- GCP managed databases (CloudSQL, AlloyDB)
- Integrate with existing database infrastructure
- Scale to distributed deployments

### Available Backends

| Backend | Type | Embedding Strategy | Best For |
|---------|------|--------------------|----------|
| **LanceDB** | Embedded | Local (SentenceTransformer) | Development, prototyping |
| **PostgreSQL** | Self-hosted | Local (SentenceTransformer) | Self-hosted production |
| **CloudSQL** | GCP managed | Local (SentenceTransformer) | GCP deployments with connection pooling constraints |
| **AlloyDB** | GCP managed | Server-side (Vertex AI text-embedding-005) | GCP production, fastest indexing |

**Embedding Strategies:**
- **Local**: Uses SentenceTransformer `all-MiniLM-L6-v2` model (384 dimensions) on client side
- **Server-side**: Uses Vertex AI `text-embedding-005` (768 dimensions) via database extension (AlloyDB only)

**Unified PostgreSQL Provider**: CloudSQL and AlloyDB use the same provider implementation (`storage/providers/postgresql/`) with different configuration. The `embedding_strategy` setting determines whether embeddings are generated locally or server-side.

### LanceDB (Default)

Best for local development and prototyping:

- **Embedded**: No separate server process required
- **Fast**: Optimized for vector and full-text search
- **ACID**: Transactional guarantees
- **Columnar**: Efficient storage and query performance
- **Integrated**: Vector + FTS + metadata in one system

Configure LanceDB via `agentic-inquiry.yaml`:

```yaml
storage:
  backend: lancedb
  backends:
    lancedb:
      type: lancedb
      uri: "./vector_db"  # Local path or cloud URI
```

### PostgreSQL

Best for self-hosted production deployments:

```yaml
storage:
  backend: postgresql
  backends:
    postgresql:
      type: postgresql
      embedding_strategy: local  # Client-side embedding
      embedding_model: all-MiniLM-L6-v2
      embedding_dim: 384
      host: localhost
      port: 5432
      database: agentic-inquiry
      user: ai_user
      password: ${POSTGRES_PASSWORD}
      pool_size: 10
      max_overflow: 5
```

### CloudSQL (GCP)

Best for GCP deployments with connection pooling:

```yaml
storage:
  backend: cloudsql
  backends:
    cloudsql:
      type: cloudsql
      embedding_strategy: local  # Client-side embedding
      embedding_model: all-MiniLM-L6-v2
      embedding_dim: 384
      instance_connection_name: project:region:instance
      database: agentic-inquiry
      user: ai_user
      password: ${GCP_PASSWORD}
      pool_size: 5  # CloudSQL has max_connections=25
      max_overflow: 2
```

**Note**: CloudSQL has connection limit constraints (max_connections=25). Use conservative pool settings.

### AlloyDB (GCP Production)

Best for GCP production with fastest indexing:

```yaml
storage:
  backend: alloydb
  backends:
    alloydb:
      type: alloydb
      embedding_strategy: server_side  # Vertex AI embedding
      embedding_model: text-embedding-005
      embedding_dim: 768
      instance_connection_name: projects/PROJECT/locations/REGION/clusters/CLUSTER/instances/INSTANCE
      database: agentic-inquiry
      user: postgres
      password: ${ALLOYDB_PASSWORD}
      pool_size: 10
      max_overflow: 5
```

**Server-side embedding benefits:**
- 10-27x faster indexing (no client-side embedding overhead)
- Batch embedding via `ai.initialize_embeddings()` at ~400 chunks/sec
- Automatic embedding generation after indexing
- Higher dimensional embeddings (768 vs 384)

**AlloyDB requirements:**
- Database flag: `google_ml_integration.enable_faster_embedding_generation=on`
- Extension: `google_ml_integration` (auto-installed by provider)
- Vertex AI API enabled for the GCP project

### Storage Facade Interface

The `StorageFacade` class provides the unified storage interface:

```python
from agentic_inquiry.storage.facade import StorageFacade

class StorageFacade:
    """Unified storage interface across all backends."""

    @classmethod
    async def from_config(cls, config: Config, project_id: str) -> "StorageFacade":
        """Create facade from configuration."""
        pass

    async def upsert_chunks(self, chunks: List[Any]) -> None:
        """Add or update document chunks."""
        pass

    async def hybrid_search(
        self,
        query_vector: Union[List[float], str],
        query_fts: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Perform hybrid search combining vector + FTS.

        Note: query_vector can be a string for server-side embedding backends
        (AlloyDB) or a List[float] for local embedding backends.
        """
        pass

    async def close(self) -> None:
        """Close all provider connections."""
        pass
```

**Embedding Strategy Handling:**

For local embedding (LanceDB, PostgreSQL, CloudSQL):
```python
# Generate embedding locally
from agentic_inquiry.embeddings.service import EmbeddingService
embedding_service = EmbeddingService(config)
query_vector = await embedding_service.embed_async(query_text)

# Search with vector
results = await facade.hybrid_search(
    query_vector=query_vector,  # List[float]
    query_fts=query_text,
    limit=10,
)
```

For server-side embedding (AlloyDB):
```python
# Pass query text directly - server generates embedding
results = await facade.hybrid_search(
    query_vector=query_text,  # str - server-side embedding
    query_fts=query_text,
    limit=10,
)
```

### Requirements for Alternative Backends

Any alternative backend must support:

1. **Vector similarity search** with cosine distance
2. **Full-text search** with keyword matching
3. **Metadata filtering** with complex expressions
4. **Batch operations** for efficient indexing
5. **Transactions** or consistency guarantees
6. **Schema flexibility** for varying metadata

**Provider Structure:**

Backends are implemented as pairs of providers:
- **VectorProvider**: Handles document chunks, vector search, FTS, hybrid search
- **GraphProvider**: Handles entities, relationships, graph traversal

See `storage/providers/postgresql/` for the reference implementation used by PostgreSQL, CloudSQL, and AlloyDB backends.

**Schema Configuration:**

Backend schemas are defined in `storage/schemas/*.schema.json`:
- `lancedb.schema.json` - LanceDB schema
- `postgresql.schema.json` - PostgreSQL/CloudSQL base schema
- `alloydb.schema.json` - AlloyDB extensions (embedding_strategy, GCP connection params)

Each schema defines required tables, columns, indexes, and backend-specific features.

### Implementing a Custom Backend

Create provider classes implementing the storage protocols. You need both a VectorProvider and a GraphProvider.

**VectorProvider Example:**

```python
from typing import Any, Dict, List, Optional, Union
from agentic_inquiry.storage.base import BaseVectorProvider
from agentic_inquiry.search.results import SearchResult
from agentic_inquiry.config import BackendConfig

class CustomVectorProvider(BaseVectorProvider):
    """Custom vector storage backend implementation.

    Must implement:
    - initialize() / close()
    - upsert_chunks()
    - vector_search() / fts_search() / hybrid_search()
    - delete_by_project()
    - get_chunk_count()
    """

    def __init__(self, config: BackendConfig):
        super().__init__(config)
        self._client = None

    @classmethod
    async def from_config(cls, config: BackendConfig) -> "CustomVectorProvider":
        """Create provider from configuration."""
        provider = cls(config)
        await provider.initialize()
        return provider

    async def initialize(self) -> None:
        """Initialize connection to storage backend."""
        if self._initialized:
            return
        self._client = await self._create_client()
        self._initialized = True

    async def upsert_chunks(self, chunks: List[Dict[str, Any]]) -> None:
        """Upsert chunks to storage.

        Chunks must have:
        - id: str
        - content: str
        - embedding: List[float] (unless server-side embedding)
        - project_id: str
        - file_path: str
        - Additional metadata fields
        """
        if not chunks:
            return

        records = [self._convert_chunk(chunk) for chunk in chunks]
        await self._client.upsert("chunks", records)

    async def vector_search(
        self,
        query_vector: Union[List[float], str],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        vector_column: str = "embedding",
    ) -> List[SearchResult]:
        """Perform vector search.

        Args:
            query_vector: Embedding vector OR query text (for server-side embedding)
            limit: Max results to return
            filters: Metadata filters
            vector_column: Column containing embeddings

        Returns:
            List of SearchResult with normalized scores (0.0-1.0)
        """
        query = self._build_vector_query(query_vector, limit, filters)
        results = await self._client.search(query)
        return [self._convert_result(r) for r in results]

    async def close(self) -> None:
        """Close connections."""
        if self._client:
            await self._client.close()
            self._client = None
        self._initialized = False

    @property
    def capabilities(self) -> Dict[str, Any]:
        """Return backend capabilities."""
        return {
            "embedding_strategy": self.config.embedding_strategy,
            "supports_fts": True,
            "supports_hybrid": True,
            "supports_server_embedding": False,
        }

    def _convert_chunk(self, chunk: Dict[str, Any]) -> Dict[str, Any]:
        """Convert chunk to backend format."""
        # Your conversion logic
        pass

    def _convert_result(self, result: Any) -> SearchResult:
        """Convert backend result to SearchResult."""
        # Your conversion logic
        pass

    async def _create_client(self):
        """Create backend client."""
        # Your client creation logic
        pass
```

**GraphProvider Example:**

```python
from agentic_inquiry.storage.base import BaseGraphProvider

class CustomGraphProvider(BaseGraphProvider):
    """Custom graph storage backend implementation.

    Must implement:
    - initialize() / close()
    - upsert_entities()
    - upsert_relationships()
    - entity_vector_search()
    - get_relationships()
    - delete_by_project()
    - get_entity_count() / get_relationship_count()
    """

    # Similar structure to VectorProvider
    # See storage/providers/postgresql/graph.py for reference
    pass
```

### Integrating with StorageFacade

Register your custom provider and use it via StorageFacade:

```python
from agentic_inquiry.storage.facade import StorageFacade
from agentic_inquiry.storage.registry import StorageRegistry

# Register your custom providers
registry = StorageRegistry()
registry.register_backend(
    backend_type="custom",
    vector_provider_class=CustomVectorProvider,
    graph_provider_class=CustomGraphProvider,
)

# Configure in agentic-inquiry.yaml
# storage:
#   backend: custom
#   backends:
#     custom:
#       type: custom
#       embedding_strategy: local  # or server_side
#       embedding_model: all-MiniLM-L6-v2
#       embedding_dim: 384
#       connection_string: "..."

# Use via facade
from agentic_inquiry.config import Config

config = Config.load()
facade = await StorageFacade.from_config(config, project_id="my-project")

# Use normally
results = await facade.hybrid_search(
    query_vector=embedding,  # List[float] for local, str for server-side
    query_fts="search query",
    limit=10,
)
await facade.close()
```

**Configuration Schema:**

Add your backend to `storage/schemas/custom.schema.json`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["type"],
  "properties": {
    "type": {
      "type": "string",
      "const": "custom"
    },
    "embedding_strategy": {
      "type": "string",
      "enum": ["local", "server_side"],
      "default": "local"
    },
    "embedding_model": {
      "type": "string",
      "default": "all-MiniLM-L6-v2"
    },
    "embedding_dim": {
      "type": "integer",
      "default": 384
    },
    "connection_string": {
      "type": "string"
    }
  }
}
```

### Storage Best Practices

1. **Choose the right backend**:
   - LanceDB for local development and prototyping
   - PostgreSQL for self-hosted production
   - AlloyDB for GCP production with fastest indexing
   - CloudSQL for GCP deployments with connection constraints

2. **Understand embedding strategies**:
   - Local: Client-side embedding, works everywhere, 384 dims
   - Server-side: Database-side embedding, AlloyDB only, 768 dims, 10-27x faster indexing

3. **Configure connection pools**:
   - LanceDB: No pooling needed (embedded)
   - PostgreSQL: pool_size=10, max_overflow=5 (typical)
   - CloudSQL: pool_size=5, max_overflow=2 (max_connections=25 limit)
   - AlloyDB: pool_size=10, max_overflow=5 (no connection limit)

4. **Test thoroughly**: Verify all operations work correctly
5. **Monitor performance**: Track latency and throughput
6. **Handle errors**: Implement retry logic and fallbacks
7. **Batch operations**: Reduce network overhead
8. **Version your data**: Track schema changes
9. **Backup regularly**: Ensure data durability

**Provider Implementation Reference:**

See `storage/providers/postgresql/` for the production-ready implementation used by PostgreSQL, CloudSQL, and AlloyDB backends. This is the canonical example of:
- Unified provider supporting multiple backends
- Local vs server-side embedding strategy
- Connection pooling and lifecycle management
- Hybrid search with RRF reranking
- Schema management and migrations

## Testing Your Extensions

### Parser Testing

```python
import pytest
from pathlib import Path
from agentic_inquiry.parsers.models import ParsedDocument

def test_parser_basic():
    parser = CustomParser()
    
    test_file = Path("test.custom")
    test_file.write_text("test content")
    
    try:
        doc = parser.parse(str(test_file))
        assert isinstance(doc, ParsedDocument)
        assert len(doc.chunks) > 0
    finally:
        test_file.unlink()

def test_parser_can_parse():
    parser = CustomParser()
    assert parser.can_parse("file.custom")
    assert not parser.can_parse("file.txt")
```

### Embedder Testing

```python
import pytest
import numpy as np

def test_embedder_basic():
    embedder = CustomEmbedder(ndims=128)
    
    texts = ["hello world", "test document"]
    embeddings = embedder.generate(texts)
    
    assert len(embeddings) == 2
    assert len(embeddings[0]) == 128
    assert all(isinstance(v, float) for v in embeddings[0])

def test_embedder_consistency():
    embedder = CustomEmbedder()
    
    text = "consistent text"
    emb1 = embedder.generate([text])[0]
    emb2 = embedder.generate([text])[0]
    
    assert np.allclose(emb1, emb2)
```

### Search Testing

```python
def test_search_configuration():
    """Test search with custom configuration."""
    results = await search_service.hybrid_search(
        query_vector=embedding,
        query_fts="test query",
        limit=10,
    )
    
    assert len(results) <= 10
    assert all("id" in r for r in results)
```

## See Also

- [Architecture Overview](../architecture/overview.md) - System architecture
- [API Reference](../api-reference/api.md) - Complete API documentation
- [Adapter Implementation Guide](../development/adapter-implementation-guide.md) - Detailed backend implementation guide
- [Storage Providers](../../agentic-inquiry/storage/providers/) - Reference implementations
