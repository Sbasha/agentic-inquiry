# Adapter Implementation Guide

> Historical reference. This page describes PostgreSQL-family providers, cloud connectors or remote embedders that are not part of this local-only distribution. It is retained as design input for the external provider contract in [storage-backends.md](../storage-backends.md).

This guide is for engineers implementing a new database adapter (vector store, graph store) for Agentic Inquiry.

## Prerequisites

- Understand the current storage architecture (see below)
- Review existing provider implementations in `agentic_inquiry/storage/providers/`
- Understand embedding strategies (local vs server-side)
- Review configuration schemas in `agentic_inquiry/storage/schemas/`

## Current Storage Architecture

Agentic Inquiry uses a provider-based storage architecture with four production backends:

| Backend | Providers | Location | Embedding Strategy |
|---------|-----------|----------|-------------------|
| **LanceDB** | LanceVectorProvider, LanceGraphProvider | `storage/providers/lancedb/` | Local (SentenceTransformer) |
| **PostgreSQL** | PostgresVectorProvider, PostgresGraphProvider | `storage/providers/postgresql/` | Local (SentenceTransformer) |
| **CloudSQL** | PostgresVectorProvider, PostgresGraphProvider | `storage/providers/postgresql/` | Local (SentenceTransformer) |
| **AlloyDB** | PostgresVectorProvider, PostgresGraphProvider | `storage/providers/postgresql/` | Server-side (Vertex AI) |

**Unified PostgreSQL Provider**: The `storage/providers/postgresql/` package implements a single provider that supports PostgreSQL, CloudSQL, and AlloyDB. The `embedding_strategy` configuration option determines whether embeddings are generated locally or server-side.

**Reference Implementation**: Use `storage/providers/postgresql/` as the canonical example for new backend implementations.

## What "Done" Means

An adapter is "production-ready" when it:

- Implements both VectorProvider and GraphProvider base classes
- Supports vector search, full-text search, and hybrid search
- Handles local and/or server-side embedding strategies
- Implements proper connection pooling and lifecycle management
- Passes integration tests with real data
- Has documented capabilities and limitations
- Includes configuration schema in `storage/schemas/`

## Implementation Checklist

### 1) Provider Base Classes

Implement both provider types by extending base classes:

**VectorProvider** (`storage/base.py: BaseVectorProvider`):
- Lifecycle: `initialize()` / `close()`
- CRUD: `upsert_chunks()` / `delete_by_project()`
- Search: `vector_search()` / `fts_search()` / `hybrid_search()`
- Queries: `get_chunk_count()` / `get_chunks_by_file()`
- Properties: `capabilities` (embedding_strategy, supports_fts, etc.)

**GraphProvider** (`storage/base.py: BaseGraphProvider`):
- Lifecycle: `initialize()` / `close()`
- CRUD: `upsert_entities()` / `upsert_relationships()` / `delete_by_project()`
- Search: `entity_vector_search()` / `get_entity()` / `get_relationships()`
- Queries: `get_entity_count()` / `get_relationship_count()`
- Properties: `capabilities`

### 2) Embedding Strategy Support

Choose one or both embedding strategies:

**Local Embedding** (all backends):
- Client generates embeddings using SentenceTransformer
- Provider stores pre-computed embedding vectors
- `upsert_chunks()` receives chunks with `embedding: List[float]`
- `vector_search()` receives `query_vector: List[float]`
- Default model: `all-MiniLM-L6-v2` (384 dimensions)

**Server-Side Embedding** (database-native):
- Database generates embeddings via extension/function
- Provider stores chunks WITHOUT embeddings
- `upsert_chunks()` receives chunks with `embedding: None`
- `vector_search()` receives `query_vector: str` (raw text)
- Post-indexing: call provider's `generate_embeddings()` method
- Example: AlloyDB with `text-embedding-005` (768 dimensions)

Set `embedding_strategy` in provider config:
```python
@property
def capabilities(self) -> Dict[str, Any]:
    return {
        "embedding_strategy": "local",  # or "server_side"
        "supports_fts": True,
        "supports_hybrid": True,
        "supports_server_embedding": False,  # True for AlloyDB
    }
```

### 3) Schema and Table Management

Implement schema initialization in `initialize()`:

**Required tables for VectorProvider:**
- `chunks`: Document chunks with content, embeddings, metadata
- `chunks_fts`: Full-text search index (if supported)

**Required tables for GraphProvider:**
- `entities`: Code entities (functions, classes, etc.)
- `relationships`: Connections between entities

**Schema Requirements:**
- All tables must have `id` (str) and `project_id` (str) columns
- Vector columns must match configured embedding dimensions
- Create indexes for: id, project_id, file_path, vector similarity
- At least one FTS index covering `fts_text` (if supported; PostgreSQL also weights `file_path`)

**Reference schemas:**
- `storage/schemas/postgresql.schema.json` - PostgreSQL base schema
- `storage/schemas/alloydb.schema.json` - AlloyDB extensions
- `storage/schemas/lancedb.schema.json` - LanceDB schema

### 4) Search Implementation

Implement all three search modes:

**Vector Search** (`vector_search()`):
- Query by embedding similarity
- For local: accept `List[float]` query vector
- For server-side: accept `str` query text, generate embedding in database
- Return results sorted by similarity (descending)
- Normalize scores to 0.0-1.0 range

**Full-Text Search** (`fts_search()`):
- Query by keyword matching
- Support CamelCase/snake_case splitting
- Return results sorted by relevance
- Normalize scores to 0.0-1.0 range

**Hybrid Search** (`hybrid_search()`):
- Combine vector + FTS results
- Use reciprocal rank fusion (RRF) for merging
- Apply IDF-weighted content boost
- Deduplicate results (max 2 per file)
- See `storage/providers/postgresql/vector.py` for reference implementation

### 5) Connection Management

Implement proper lifecycle management:

**Connection Pooling:**
- Use async connection pools (asyncpg, aiosqlite, etc.)
- Configure `pool_size` and `max_overflow` from config
- Handle connection errors with retries
- Clean up connections on `close()`

**Initialization:**
- `initialize()` must be idempotent (safe to call multiple times)
- Create tables/indexes if they don't exist
- Validate schema compatibility
- Test connection before returning

**Cleanup:**
- `close()` must release all resources
- Safe to call multiple times
- No dangling connections

### 6) Configuration and Registry

**Configuration Schema:**

Create `storage/schemas/yourbackend.schema.json`:
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["type"],
  "properties": {
    "type": {"type": "string", "const": "yourbackend"},
    "embedding_strategy": {
      "type": "string",
      "enum": ["local", "server_side"],
      "default": "local"
    },
    "embedding_model": {"type": "string"},
    "embedding_dim": {"type": "integer"},
    "connection_string": {"type": "string"}
  }
}
```

**Registry Registration:**

In `storage/registry.py`:
```python
registry.register_backend(
    backend_type="yourbackend",
    vector_provider_class=YourVectorProvider,
    graph_provider_class=YourGraphProvider,
)
```

### 7) Tests (Required)

Add integration tests:
- Basic CRUD: insert, upsert, delete, get
- Search: vector, FTS, hybrid with real data
- Lifecycle: initialize, close, reconnect
- Error handling: connection failures, invalid data
- Performance: indexing speed, search latency

See `tests/storage/` for test patterns.

## Common Pitfalls

### Embedding Strategy Confusion

**WRONG**: Mixing embedding strategies in the same provider
```python
# DON'T DO THIS
async def vector_search(self, query_vector):
    if isinstance(query_vector, str):
        # Generate embedding here
        query_vector = self._embed(query_vector)
```

**RIGHT**: Declare strategy in capabilities, validate inputs
```python
# DO THIS
@property
def capabilities(self):
    return {"embedding_strategy": "local"}

async def vector_search(self, query_vector: List[float]):
    if not isinstance(query_vector, list):
        raise ValueError("Local embedding requires List[float] query_vector")
```

### Connection Pool Leaks

**WRONG**: Creating connections without cleanup
```python
async def search(self):
    conn = await self._create_connection()  # LEAK!
    return await conn.fetch(...)
```

**RIGHT**: Use connection pools and context managers
```python
async def search(self):
    async with self._pool.acquire() as conn:
        return await conn.fetch(...)
```

### Schema Compatibility

**WRONG**: Hardcoding table/column names
```python
await conn.execute("SELECT * FROM chunks WHERE ...")
```

**RIGHT**: Use configuration and validation
```python
table_name = self.config.table_name_chunks
await self._validate_schema(table_name)
await conn.execute(f"SELECT * FROM {table_name} WHERE ...")
```

### Result Score Ranges

**WRONG**: Returning raw backend scores (can be negative, >1.0, etc.)
```python
return [SearchResult(id=r.id, score=r.distance) for r in results]
```

**RIGHT**: Normalize to 0.0-1.0 range
```python
# Convert distance to similarity
normalized_score = 1.0 / (1.0 + result.distance)
return [SearchResult(id=r.id, score=normalized_score) for r in results]
```

---

## Provider Method Contracts

Base classes define required methods. Every provider must implement them.

### BaseVectorProvider Methods

| Method | Signature | Contract |
|--------|-----------|----------|
| `initialize()` | `async def initialize() -> None` | Idempotent setup. Create tables/indexes. Test connection. |
| `close()` | `async def close() -> None` | Release all connections. Safe to call multiple times. |
| `upsert_chunks()` | `async def upsert_chunks(chunks: List[Dict]) -> None` | Insert or update chunks. Handle embedding strategy. |
| `vector_search()` | `async def vector_search(query_vector, limit, filters) -> List[SearchResult]` | Search by embedding similarity. Normalize scores to 0.0-1.0. |
| `fts_search()` | `async def fts_search(query_fts, limit, filters) -> List[SearchResult]` | Full-text search. Normalize scores to 0.0-1.0. |
| `hybrid_search()` | `async def hybrid_search(query_vector, query_fts, limit, filters) -> List[SearchResult]` | Combined vector + FTS with RRF. Normalize scores. |
| `delete_by_project()` | `async def delete_by_project(project_id: str) -> int` | Delete all chunks for project. Return count. |
| `get_chunk_count()` | `async def get_chunk_count(project_id: str) -> int` | Count chunks for project. |
| `capabilities` | `@property def capabilities() -> Dict[str, Any]` | Return embedding_strategy, supported features. |

### BaseGraphProvider Methods

| Method | Signature | Contract |
|--------|-----------|----------|
| `initialize()` | `async def initialize() -> None` | Idempotent setup. Create tables/indexes. |
| `close()` | `async def close() -> None` | Release connections. |
| `upsert_entities()` | `async def upsert_entities(entities: List[Dict]) -> None` | Insert or update entities. |
| `upsert_relationships()` | `async def upsert_relationships(rels: List[Dict]) -> None` | Insert or update relationships. |
| `entity_vector_search()` | `async def entity_vector_search(query_vector, limit, filters) -> List[SearchResult]` | Search entities by embedding. |
| `get_entity()` | `async def get_entity(entity_id: str, project_id: str) -> Optional[Dict]` | Fetch entity by ID. |
| `get_relationships()` | `async def get_relationships(entity_id: str, project_id: str) -> List[Dict]` | Get entity relationships. |
| `delete_by_project()` | `async def delete_by_project(project_id: str) -> Tuple[int, int]` | Delete entities+relationships. Return counts. |
| `get_entity_count()` | `async def get_entity_count(project_id: str) -> int` | Count entities. |
| `get_relationship_count()` | `async def get_relationship_count(project_id: str) -> int` | Count relationships. |
| `capabilities` | `@property def capabilities() -> Dict[str, Any]` | Return supported features. |

### Error Handling

All methods must:
- Raise `ValueError` for invalid input (bad records, mismatched dimensions)
- Raise `ConnectionError` for connection failures
- Raise `RuntimeError` for backend failures
- Never silently fail or return partial results
- Log errors with context (use lazy logging: `logger.info("msg %s", var)`)

---

## Capability Declaration

Providers declare their capabilities via the `capabilities` property:

```python
@property
def capabilities(self) -> Dict[str, Any]:
    """Return backend capabilities."""
    return {
        # Embedding strategy (required)
        "embedding_strategy": "local",  # or "server_side"

        # Search capabilities (required)
        "supports_fts": True,
        "supports_hybrid": True,

        # Server-side embedding (optional)
        "supports_server_embedding": False,  # True for AlloyDB

        # Additional capabilities (optional)
        "supports_async": True,
        "supports_transactions": False,
        "max_vector_dims": 2048,
    }
```

The app layer checks capabilities before using features:

```python
from agentic_inquiry.storage.facade import StorageFacade

facade = await StorageFacade.from_config(config, project_id="test")

# Check embedding strategy
if facade.vector_provider.capabilities["embedding_strategy"] == "server_side":
    # Pass raw text for server-side embedding
    results = await facade.hybrid_search(
        query_vector="authentication logic",  # str
        query_fts="authentication logic",
    )
else:
    # Generate embedding locally
    embedding = await embedding_service.embed_async("authentication logic")
    results = await facade.hybrid_search(
        query_vector=embedding,  # List[float]
        query_fts="authentication logic",
    )
```

---

## Example: PostgreSQL Provider as Reference

The PostgreSQL provider is the canonical reference implementation. It demonstrates:

- **Unified backend support**: One provider for PostgreSQL, CloudSQL, and AlloyDB
- **Dual embedding strategies**: Local (SentenceTransformer) and server-side (Vertex AI)
- **Hybrid search**: Vector + FTS with RRF reranking
- **Connection pooling**: Async connection management with configurable pool sizes
- **Schema management**: Dynamic schema creation and validation
- **Error handling**: Comprehensive error handling with retries

**Key files:**
- `storage/providers/postgresql/vector.py` - VectorProvider implementation
- `storage/providers/postgresql/graph.py` - GraphProvider implementation
- `storage/providers/postgresql/connection.py` - Connection management
- `storage/schemas/postgresql.schema.json` - Base schema
- `storage/schemas/alloydb.schema.json` - AlloyDB extensions

**Study this implementation** before creating a new backend.

---

## Example: Minimal Provider Skeleton

Copy this as a starting point for a new provider:

```python
"""Minimal VectorProvider skeleton."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
import logging

from agentic_inquiry.config import BackendConfig
from agentic_inquiry.storage.base import BaseVectorProvider
from agentic_inquiry.search.results import SearchResult

logger = logging.getLogger(__name__)


class MinimalVectorProvider(BaseVectorProvider):
    """Minimal vector provider implementation.

    Lifecycle:
        provider = await MinimalVectorProvider.from_config(config)
        # provider.initialize() called automatically
        # ... use provider ...
        await provider.close()
    """

    def __init__(self, config: BackendConfig) -> None:
        super().__init__(config)
        self._client = None

    @classmethod
    async def from_config(cls, config: BackendConfig) -> "MinimalVectorProvider":
        """Create and initialize provider from configuration."""
        provider = cls(config)
        await provider.initialize()
        return provider

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def initialize(self) -> None:
        """Initialize connection and create schema."""
        if self._initialized:
            return

        logger.info("Initializing MinimalVectorProvider")

        # TODO: Create connection/client
        self._client = await self._create_client()

        # TODO: Create tables and indexes
        await self._create_schema()

        self._initialized = True
        logger.info("MinimalVectorProvider initialized")

    async def close(self) -> None:
        """Close connections and release resources."""
        if self._client:
            logger.info("Closing MinimalVectorProvider")
            await self._client.close()
            self._client = None

        self._initialized = False

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    async def upsert_chunks(self, chunks: List[Dict[str, Any]]) -> None:
        """Insert or update document chunks.

        Args:
            chunks: List of chunk dicts with:
                - id: str
                - content: str
                - embedding: List[float] (for local) or None (for server-side)
                - project_id: str
                - file_path: str
                - Additional metadata
        """
        if not chunks:
            return

        logger.info("Upserting %s chunks", len(chunks))

        # TODO: Insert/update chunks in backend
        # Handle embedding strategy (local vs server-side)
        # Batch for efficiency
        raise NotImplementedError

    async def delete_by_project(self, project_id: str) -> int:
        """Delete all chunks for a project.

        Args:
            project_id: Project identifier

        Returns:
            Number of chunks deleted
        """
        logger.info("Deleting chunks for project %s", project_id)

        # TODO: Delete chunks WHERE project_id = ?
        # Return count of deletions
        raise NotImplementedError

    # =========================================================================
    # Search Operations
    # =========================================================================

    async def vector_search(
        self,
        query_vector: Union[List[float], str],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        vector_column: str = "embedding",
    ) -> List[SearchResult]:
        """Search by vector similarity.

        Args:
            query_vector: Embedding (List[float] for local, str for server-side)
            limit: Max results
            filters: Metadata filters
            vector_column: Column containing embeddings

        Returns:
            SearchResults with normalized scores (0.0-1.0)
        """
        logger.info("Vector search: limit=%s", limit)

        # TODO: Execute vector similarity search
        # Apply filters
        # Normalize scores to 0.0-1.0
        # Return SearchResult objects
        raise NotImplementedError

    async def fts_search(
        self,
        query_fts: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Full-text search.

        Args:
            query_fts: Search query
            limit: Max results
            filters: Metadata filters

        Returns:
            SearchResults with normalized scores (0.0-1.0)
        """
        logger.info("FTS search: query=%s, limit=%s", query_fts, limit)

        # TODO: Execute full-text search
        # Apply filters
        # Normalize scores to 0.0-1.0
        # Return SearchResult objects
        raise NotImplementedError

    async def hybrid_search(
        self,
        query_vector: Union[List[float], str],
        query_fts: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Combined vector + FTS search with RRF.

        Args:
            query_vector: Embedding or text
            query_fts: Search query
            limit: Max results
            filters: Metadata filters

        Returns:
            Merged and reranked SearchResults
        """
        logger.info("Hybrid search: limit=%s", limit)

        # TODO: Run vector + FTS searches
        # Merge with reciprocal rank fusion (RRF)
        # Apply IDF-weighted content boost
        # Deduplicate (max 2 per file)
        # See storage/providers/postgresql/vector.py for reference
        raise NotImplementedError

    # =========================================================================
    # Queries
    # =========================================================================

    async def get_chunk_count(self, project_id: str) -> int:
        """Count chunks for a project."""
        logger.info("Getting chunk count for project %s", project_id)

        # TODO: SELECT COUNT(*) WHERE project_id = ?
        raise NotImplementedError

    # =========================================================================
    # Capabilities
    # =========================================================================

    @property
    def capabilities(self) -> Dict[str, Any]:
        """Return backend capabilities."""
        return {
            "embedding_strategy": "local",  # or "server_side"
            "supports_fts": True,
            "supports_hybrid": True,
            "supports_server_embedding": False,
        }

    # =========================================================================
    # Private Helpers
    # =========================================================================

    async def _create_client(self) -> Any:
        """Create backend client/connection."""
        # TODO: Initialize connection to backend
        raise NotImplementedError

    async def _create_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        # TODO: CREATE TABLE IF NOT EXISTS chunks (...)
        # TODO: CREATE INDEX IF NOT EXISTS idx_project_id ON chunks(project_id)
        # TODO: CREATE INDEX IF NOT EXISTS idx_vector ON chunks USING ivfflat(embedding)
        # TODO: CREATE INDEX IF NOT EXISTS idx_fts ON chunks USING gin(to_tsvector(...))
        raise NotImplementedError
```

---

## Example: Custom Backend Integration

This example shows how to integrate a custom backend (e.g., Qdrant) with Agentic Inquiry:

```python
"""Example: Qdrant VectorProvider implementation."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
import logging

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter as QdrantFilter

from agentic_inquiry.config import BackendConfig
from agentic_inquiry.storage.base import BaseVectorProvider
from agentic_inquiry.search.results import SearchResult

logger = logging.getLogger(__name__)


class QdrantVectorProvider(BaseVectorProvider):
    """Qdrant vector provider implementation.

    Features:
    - Vector search with native Qdrant similarity
    - Local embedding strategy only (no FTS/hybrid)
    - Metadata filtering via Qdrant filters

    Limitations:
    - No native FTS support
    - No hybrid search (app-layer fallback required)
    """

    def __init__(self, config: BackendConfig) -> None:
        super().__init__(config)
        self._client: Optional[AsyncQdrantClient] = None
        self._collection_name = "ai_chunks"

    @classmethod
    async def from_config(cls, config: BackendConfig) -> "QdrantVectorProvider":
        """Create and initialize provider from configuration."""
        provider = cls(config)
        await provider.initialize()
        return provider

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def initialize(self) -> None:
        """Initialize Qdrant client and create collection."""
        if self._initialized:
            return

        logger.info("Initializing QdrantVectorProvider: url=%s", self.config.url)

        # Create client
        self._client = AsyncQdrantClient(
            url=self.config.url,
            api_key=self.config.api_key,
        )

        # Create collection if it doesn't exist
        collections = await self._client.get_collections()
        if not any(c.name == self._collection_name for c in collections.collections):
            logger.info("Creating collection: %s", self._collection_name)
            await self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=VectorParams(
                    size=self.config.embedding_dim,
                    distance=Distance.COSINE,
                ),
            )

        self._initialized = True
        logger.info("QdrantVectorProvider initialized")

    async def close(self) -> None:
        """Close Qdrant client."""
        if self._client:
            logger.info("Closing QdrantVectorProvider")
            await self._client.close()
            self._client = None

        self._initialized = False

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    async def upsert_chunks(self, chunks: List[Dict[str, Any]]) -> None:
        """Upsert chunks to Qdrant."""
        if not chunks:
            return

        logger.info("Upserting %s chunks to Qdrant", len(chunks))

        points = [
            PointStruct(
                id=chunk["id"],
                vector=chunk["embedding"],
                payload={
                    k: v
                    for k, v in chunk.items()
                    if k not in ("id", "embedding")
                },
            )
            for chunk in chunks
        ]

        await self._client.upsert(
            collection_name=self._collection_name,
            points=points,
        )

    async def delete_by_project(self, project_id: str) -> int:
        """Delete all chunks for a project."""
        logger.info("Deleting chunks for project: %s", project_id)

        # Count before delete
        count = await self.get_chunk_count(project_id)

        # Delete by project_id filter
        await self._client.delete(
            collection_name=self._collection_name,
            points_selector=QdrantFilter(
                must=[
                    {"key": "project_id", "match": {"value": project_id}}
                ]
            ),
        )

        return count

    # =========================================================================
    # Search Operations
    # =========================================================================

    async def vector_search(
        self,
        query_vector: Union[List[float], str],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        vector_column: str = "embedding",
    ) -> List[SearchResult]:
        """Vector search with Qdrant."""
        if isinstance(query_vector, str):
            raise ValueError("Qdrant only supports local embedding (List[float])")

        logger.info("Vector search: limit=%s", limit)

        # Build Qdrant filter
        qdrant_filter = self._build_filter(filters) if filters else None

        # Search
        results = await self._client.search(
            collection_name=self._collection_name,
            query_vector=query_vector,
            limit=limit,
            query_filter=qdrant_filter,
        )

        return [
            SearchResult(
                id=str(r.id),
                score=r.score,  # Qdrant returns similarity (0-1) natively
                data=r.payload,
            )
            for r in results
        ]

    async def fts_search(
        self,
        query_fts: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """FTS not supported by Qdrant."""
        raise NotImplementedError("Qdrant does not support FTS - use app-layer fallback")

    async def hybrid_search(
        self,
        query_vector: Union[List[float], str],
        query_fts: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Hybrid not supported by Qdrant."""
        raise NotImplementedError("Qdrant does not support hybrid search - use app-layer fallback")

    # =========================================================================
    # Queries
    # =========================================================================

    async def get_chunk_count(self, project_id: str) -> int:
        """Count chunks for a project."""
        result = await self._client.count(
            collection_name=self._collection_name,
            count_filter=QdrantFilter(
                must=[{"key": "project_id", "match": {"value": project_id}}]
            ),
        )
        return result.count

    # =========================================================================
    # Capabilities
    # =========================================================================

    @property
    def capabilities(self) -> Dict[str, Any]:
        """Return Qdrant capabilities."""
        return {
            "embedding_strategy": "local",
            "supports_fts": False,
            "supports_hybrid": False,
            "supports_server_embedding": False,
        }

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _build_filter(self, filters: Dict[str, Any]) -> QdrantFilter:
        """Build Qdrant filter from ai filter dict."""
        # TODO: Implement filter translation
        # Convert ai filters to Qdrant filter format
        raise NotImplementedError
```

### Key Implementation Notes

1. **Qdrant returns similarity scores** (not distances), so no normalization needed
2. **FTS is not implemented** - raises `NotImplementedError` to trigger app-layer fallback
3. **Hybrid is not implemented** - app layer must run vector + FTS separately and merge
4. **Filter translation** - needs Qdrant-specific filter builder
5. **Collection creation** happens in `initialize()` with auto-create

---

## Integration Checklist

After implementing your provider:

### 1. Configuration Schema

Create `storage/schemas/yourbackend.schema.json`:
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["type"],
  "properties": {
    "type": {"type": "string", "const": "yourbackend"},
    "embedding_strategy": {
      "type": "string",
      "enum": ["local", "server_side"],
      "default": "local"
    },
    "url": {"type": "string"},
    "api_key": {"type": "string"}
  }
}
```

### 2. Registry Registration

In `storage/registry.py`:
```python
# Import your providers
from agentic_inquiry.storage.providers.yourbackend.vector import YourVectorProvider
from agentic_inquiry.storage.providers.yourbackend.graph import YourGraphProvider

# Register in _initialize_builtin_backends()
registry.register_backend(
    backend_type="yourbackend",
    vector_provider_class=YourVectorProvider,
    graph_provider_class=YourGraphProvider,
)
```

### 3. Configuration Validation

In `storage/config.py`, add validation function if needed:
```python
def validate_yourbackend_config(config: BackendConfig) -> BackendConfig:
    """Validate YourBackend-specific configuration."""
    if config.embedding_strategy == "server_side":
        raise ValueError("YourBackend does not support server-side embedding")
    return config
```

### 4. Tests

Create `tests/storage/providers/test_yourbackend.py`:
```python
import pytest
from agentic_inquiry.config import BackendConfig
from agentic_inquiry.storage.providers.yourbackend.vector import YourVectorProvider

@pytest.mark.asyncio
async def test_provider_lifecycle():
    config = BackendConfig(
        type="yourbackend",
        embedding_strategy="local",
        url="http://localhost:6333",
    )
    provider = await YourVectorProvider.from_config(config)
    assert provider._initialized
    await provider.close()
    assert not provider._initialized

@pytest.mark.asyncio
async def test_upsert_and_search():
    # Test CRUD operations
    # Test vector search
    # Test error handling
    pass
```

### 5. Documentation

Update:
- This guide with backend-specific notes
- `docs/customization/extending.md` with backend in comparison table
- `README.md` with supported backends list

---

## See Also

- **Reference Implementation**: `storage/providers/postgresql/` - Production-ready unified provider
- **Base Classes**: `storage/base.py` - BaseVectorProvider, BaseGraphProvider
- **Configuration**: `storage/config.py` - BackendConfig, validation
- **Registry**: `storage/registry.py` - StorageRegistry, backend registration
- **Facade**: `storage/facade.py` - StorageFacade interface
- **Extending Guide**: `docs/customization/extending.md` - User-facing extension guide
