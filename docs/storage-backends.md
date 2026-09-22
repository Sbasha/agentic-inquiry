# Pluggable Storage Backends

This document describes how to configure and use pluggable storage backends in Agent-Vault.

## Overview

Agent-Vault supports multiple storage backends for different storage roles:

| Role | Description | Supported Backends |
|------|-------------|-------------------|
| `vector` | Vector embeddings and search | LanceDB, PostgreSQL, AlloyDB |
| `graph` | Entity and relationship graphs | LanceDB, PostgreSQL, AlloyDB |
| `events` | Event/audit logging | SQLite, PostgreSQL |
| `file_tracker` | File change tracking | SQLite, PostgreSQL |

**Note:** PostgreSQL, AlloyDB, and CloudSQL all use the **unified PostgreSQL provider** with different configuration options.

## Configuration

### New-Style Configuration (Recommended)

Use named backends with explicit role assignments:

```yaml
storage:
  root: "/data/agent-vault"

  # Define named backends
  backends:
    default:
      type: lancedb
      uri: "${storage.root}/lancedb"

    primary_db:
      type: postgresql
      host: localhost
      port: 5432
      database: agent-vault
      user: ${POSTGRES_USER}
      password: ${POSTGRES_PASSWORD}

    local_sqlite:
      type: sqlite
      path: "${storage.root}/local.db"

  # Assign backends to roles
  vector_backend: default
  graph_backend: default
  events_backend: local_sqlite
  file_tracker_backend_v2: local_sqlite
```

### Legacy Configuration (Backward Compatible)

For simple deployments, the legacy single-provider mode still works:

```yaml
storage:
  root: "/data/agent-vault"
  lancedb:
    uri: "${storage.root}/lancedb"
```

## Backend Types

### LanceDB (Default)

Embedded vector database with zero-configuration setup.

```yaml
backends:
  lancedb_local:
    type: lancedb
    uri: /path/to/lancedb
```

### PostgreSQL

Production-grade backend with full ACID compliance. This is the **unified provider** that also handles CloudSQL and AlloyDB.

```yaml
backends:
  postgres_primary:
    type: postgresql
    host: localhost
    port: 5432
    database: agent-vault
    user: ${POSTGRES_USER}
    password: ${POSTGRES_PASSWORD}
    pool_size: 20
    max_overflow: 10

    # Embedding strategy
    embedding_strategy: local  # "local" or "server_side" (AlloyDB only)
    embedding_model: all-MiniLM-L6-v2
    embedding_dim: 384
```

Required extension: `pgvector` for vector storage.

### AlloyDB

GCP-managed PostgreSQL with server-side embedding support. Uses the **unified PostgreSQL provider** with `embedding_strategy: server_side`.

```yaml
backends:
  alloydb:
    type: alloydb  # Maps to PostgreSQL provider internally
    project: your-gcp-project
    region: us-central1
    cluster: your-cluster
    instance: your-instance
    database: agent-vault
    user: postgres
    password: ${ALLOYDB_PASSWORD}

    # Server-side embedding (auto-configured by validate_alloydb_config)
    embedding_strategy: server_side
    embedding_model: text-embedding-005
    embedding_dim: 768

    # Connection pooling
    pool_size: 5
    max_overflow: 2
```

**Key Differences from Standard PostgreSQL:**
- **Server-side embedding:** Pipeline skips local embedding, uses AlloyDB's `text-embedding-005` model
- **Auto-embedding generation:** Calls `generate_embeddings()` after indexing
  - Fresh tables: `ai.initialize_embeddings()` at ~136-400 chunks/sec
  - Incremental: per-row `embedding()` at ~25-35 chunks/sec
- **Search:** Pass query text directly, AlloyDB generates embeddings server-side
- **Performance:** 16.6 files/sec average (27x faster than GENERATED ALWAYS AS approach)

**Architecture:** Registry maps backend type `"alloydb"` → `PostgresVectorProvider` + `PostgresGraphProvider`. The old `storage/providers/alloydb/` package is dead code.

### SQLite

Lightweight local storage for events and file tracking.

```yaml
backends:
  sqlite_local:
    type: sqlite
    path: /path/to/database.db
```

## Mixed Backends

You can use different backends for different roles:

```yaml
storage:
  backends:
    lancedb:
      type: lancedb
      uri: /data/vectors

    postgres:
      type: postgresql
      host: db.example.com
      database: agent-vault

    sqlite:
      type: sqlite
      path: /data/local.db

  # Fast local vector search
  vector_backend: lancedb

  # Centralized graph for team access
  graph_backend: postgres

  # Local event logging
  events_backend: sqlite

  # Local file tracking
  file_tracker_backend_v2: sqlite
```

## Connection Pooling

PostgreSQL backends automatically share connection pools when using the same backend name for multiple roles. This is managed by `BackendPoolManager`.

## Programmatic Usage

### Using StorageFacade (Recommended)

The `StorageFacade` provides a unified interface across all backend types:

```python
from agent_vault.config import Config
from agent_vault.storage.facade import StorageFacade

# Create facade from config
config = Config.load()
facade = await StorageFacade.from_config(config, project_id="my-project")

# Use facade methods
await facade.upsert_chunks(chunks)
results = await facade.hybrid_search(query_embedding, "search text")

# Access individual providers if needed
vector_provider = facade.vector_provider  # PostgresVectorProvider, LanceDBVectorProvider, etc.
graph_provider = facade.graph_provider
events_provider = facade.events_provider  # May be None if not configured

# Cleanup
await facade.close()
```

**Benefits:**
- Single entry point for all storage operations
- Automatic provider selection based on configuration
- Connection pooling managed automatically
- Type-safe provider protocols

### Direct Provider Access

```python
from agent_vault.storage.registry import create_provider

# Create a specific provider
events_provider = create_provider(
    config.storage,
    role="events",
    project_id="my-project"
)
await events_provider.initialize()

# Use provider
await events_provider.write_events([event])

# Cleanup
await events_provider.close()
```

## Protocols

All providers implement typed protocols:

- `VectorStorageProtocol` - 14 methods for vector operations
- `GraphStorageProtocol` - 16+ methods for graph operations
- `EventStorageProtocol` - 9 methods for event operations
- `FileTrackerProtocol` - 14 methods for file tracking

See `agent_vault.storage.protocols` for full protocol definitions.

## Migration

### From Legacy to New-Style

1. Add `backends` section with your provider configuration
2. Add role assignments (`vector_backend`, `graph_backend`, etc.)
3. Keep existing config for backward compatibility during transition

The system automatically detects which configuration style is in use.

## Deprecations

The following methods are deprecated and will emit warnings:

- `StorageFacade.count_records()` - Use `count_chunks()` or `provider.count()`
- `StorageFacade.advanced_filter()` - Use `provider.query()`

## Requirements

- LanceDB: Included in base package
- PostgreSQL: Install with `pip install agent-vault[postgresql]`
- SQLite: Included in base package (uses aiosqlite)
