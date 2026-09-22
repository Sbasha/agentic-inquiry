# Storage Adapter Architecture

This document describes the storage adapter system, the BackendLifecycle protocol, and how to create new storage adapters.

## Overview

agv uses a modular storage system where different backends (LanceDB, PostgreSQL, etc.) implement standardized protocols. This enables:

- **Backend flexibility**: Swap between local (LanceDB) and cloud (PostgreSQL/CloudSQL) storage
- **Lazy initialization**: Resources created only when `initialize()` is called, not at import time
- **Inversion of responsibility**: Each backend owns its setup and teardown; agv core provides only configuration context

## BackendLifecycle Protocol

All storage providers must implement the `BackendLifecycle` protocol defined in `agent_vault/storage/protocols.py`:

```python
@runtime_checkable
class BackendLifecycle(Protocol):
    """Lifecycle protocol that all storage backends must implement."""

    SUPPORTED_ROLES: ClassVar[frozenset[str]]
    """Storage roles this provider supports (vector, graph, events, file_tracker)."""

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],  # Protocol allows dict; implementations may require Config
        project_id: str,
        **kwargs: Any,
    ) -> Self:
        """Factory method to create provider from configuration."""
        ...

    async def initialize(self) -> None:
        """Initialize provider resources (connections, tables, directories)."""
        ...

    async def close(self) -> None:
        """Clean up provider resources."""
        ...

    async def health_check(self) -> Dict[str, Any]:
        """Check provider health. Returns dict with 'healthy': bool."""
        ...

    @property
    def is_initialized(self) -> bool:
        """Whether the provider has been initialized."""
        ...
```

### Key Design Principles

1. **Class-level `SUPPORTED_ROLES`**: Declare which storage roles the provider implements
2. **`from_config()` factory**: Standard construction pattern from configuration
3. **`initialize()` for resources**: Create directories, connections, tables here—NOT in `__init__`
4. **`close()` for cleanup**: Release all resources
5. **`health_check()` for monitoring**: Return `{"healthy": bool, ...}` with optional diagnostics
6. **`is_initialized` property**: Track initialization state

### `from_config()` Signature Variations

The protocol defines `from_config(config: Dict[str, Any], project_id: str, **kwargs)`, but implementations vary based on their needs:

| Provider Type | Signature | Notes |
|--------------|-----------|-------|
| PostgreSQL providers | `def from_config(cls, config: Dict[str, Any], project_id: str)` | Standard synchronous factory; validates to `BackendConfig` |
| LanceDBProvider | `async def from_config(cls, config: Config, project_id: str)` | Async; requires full `Config` object |
| InMemoryProvider | `async def from_config(cls, config: Config, project_id: str)` | Async; requires full `Config` object |

**Guidelines**:
- New providers should prefer the protocol signature (`Dict[str, Any]`, `project_id`)
- Use `async def` only if construction requires I/O operations
- PostgreSQL providers validate config to `BackendConfig` and filter kwargs via `model_fields.keys()`
- The registry's `create_provider()` handles these variations automatically
- Note: Current implementations don't accept `**kwargs`; the protocol allows them for future extensibility

## Storage Roles

Four storage roles are defined:

| Role | Purpose | Example Protocol Methods |
|------|---------|-------------------------|
| `vector` | Document chunks with embeddings | `vector_search()`, `upsert_chunks()` |
| `graph` | Entity relationships | `get_entity()`, `create_relationship()` |
| `events` | Session events and memories | `store_event()`, `get_events()` |
| `file_tracker` | File indexing state | `track_file()`, `get_file_status()` |

A provider can support multiple roles. For example, `LanceDBProvider` supports `vector` and `graph`, while `InMemoryProvider` also supports `vector` and `graph` (but not `events` or `file_tracker`—use SQLite for those in testing).

## Module Structure Pattern

Complex backends should use a module structure (not a single file):

```
agent_vault/storage/providers/
├── lancedb/                    # Backend as package
│   ├── __init__.py             # Exports, backward-compat aliases
│   ├── connection.py           # LanceDBConnectionManager
│   ├── vector.py               # LanceDBVectorProvider
│   ├── graph.py                # LanceDBGraphProvider
│   └── maintenance.py          # LanceDBMaintenanceOperations
├── postgresql/                 # Same pattern
│   ├── __init__.py
│   ├── connection.py
│   ├── vector.py
│   ├── graph.py
│   ├── events.py
│   ├── file_tracker.py
│   └── schema_tracker.py
└── memory.py                   # Simple backends can be single files
```

### Connection Manager Pattern

For backends with shared resources (connections, pools), create a connection manager:

```python
class LanceDBConnectionManager:
    """Manages shared LanceDB connection and lifecycle."""

    def __init__(self, config: "Config", project_id: str) -> None:
        self._config = config
        self._project_id = project_id
        self._db_manager: Optional[LanceDBManager] = None
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def project_id(self) -> str:
        return self._project_id

    async def initialize(self) -> None:
        """Create connection and prepare resources."""
        if self._initialized:
            return

        # Create directories (backend owns this!)
        db_path = self._config.storage.get_lancedb_path()
        db_path.mkdir(parents=True, exist_ok=True)

        # Create connection
        self._db_manager = LanceDBManager(uri=str(db_path))
        await self._db_manager.connect()
        await self._db_manager.create_tables_and_indexes()

        self._initialized = True

    async def close(self) -> None:
        """Clean up connection."""
        if self._db_manager:
            await self._db_manager.close()
        self._initialized = False
```

Role-specific providers then delegate to the connection manager:

```python
class LanceDBVectorProvider:
    """LanceDB implementation of VectorStorageProtocol."""

    SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset({"vector"})

    def __init__(self, connection_manager: LanceDBConnectionManager) -> None:
        self._connection_manager = connection_manager

    @property
    def is_initialized(self) -> bool:
        return self._connection_manager.is_initialized

    async def vector_search(self, query_vector, limit, ...) -> List[SearchResult]:
        # Delegate to underlying manager
        return await self._connection_manager.db_manager.vector_search(...)
```

## Registry Configuration

Providers are registered in `agent_vault/storage/registry.py`:

```python
# Registry: backend_type -> role -> (module_path, class_name)
PROVIDER_REGISTRY: Dict[str, Dict[str, Tuple[str, str]]] = {
    "lancedb": {
        "vector": ("agent_vault.storage.providers.lancedb", "LanceDBProvider"),
        "graph": ("agent_vault.storage.providers.lancedb", "LanceDBProvider"),
    },
    "postgresql": {
        "vector": ("agent_vault.storage.providers.postgresql", "PostgresVectorProvider"),
        "graph": ("agent_vault.storage.providers.postgresql", "PostgresGraphProvider"),
        "events": ("agent_vault.storage.providers.postgresql", "PostgresEventProvider"),
        "file_tracker": ("agent_vault.storage.providers.postgresql", "PostgresFileTrackerProvider"),
    },
    "alloydb": {
        # AlloyDB maps to unified PostgreSQL providers
        # Behavior differentiated via embedding_strategy config field
        "vector": ("agent_vault.storage.providers.postgresql", "PostgresVectorProvider"),
        "graph": ("agent_vault.storage.providers.postgresql", "PostgresGraphProvider"),
        "events": ("agent_vault.storage.providers.postgresql", "PostgresEventProvider"),
        "file_tracker": ("agent_vault.storage.providers.postgresql", "PostgresFileTrackerProvider"),
    },
    "memory": {
        "vector": ("agent_vault.storage.providers.memory", "InMemoryVectorProvider"),
        "graph": ("agent_vault.storage.providers.memory", "InMemoryGraphProvider"),
        # Note: events and file_tracker not supported by InMemoryProvider
    },
}
```

## Creating a New Adapter

### Step 1: Define the Module Structure

```bash
mkdir -p agent_vault/storage/providers/mybackend/
touch agent_vault/storage/providers/mybackend/__init__.py
touch agent_vault/storage/providers/mybackend/connection.py
touch agent_vault/storage/providers/mybackend/vector.py
```

### Step 2: Create the Connection Manager

```python
# mybackend/connection.py
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from agent_vault.config import Config

class MyBackendConnectionManager:
    """Manages MyBackend connection lifecycle."""

    def __init__(self, config: "Config", project_id: str) -> None:
        self._config = config
        self._project_id = project_id
        self._client = None
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def project_id(self) -> str:
        return self._project_id

    @classmethod
    def from_config(cls, config: "Config", project_id: str, **kwargs):
        return cls(config, project_id)

    async def initialize(self) -> None:
        if self._initialized:
            return
        # Create resources HERE, not in __init__
        self._client = await create_mybackend_client(self._config)
        self._initialized = True

    async def close(self) -> None:
        if self._client:
            await self._client.close()
        self._initialized = False

    async def health_check(self) -> Dict[str, Any]:
        if not self._initialized:
            return {"healthy": False, "error": "Not initialized"}
        try:
            await self._client.ping()
            return {"healthy": True, "project_id": self._project_id}
        except Exception as e:
            return {"healthy": False, "error": str(e)}
```

### Step 3: Create Role-Specific Providers

```python
# mybackend/vector.py
from typing import ClassVar, TYPE_CHECKING

if TYPE_CHECKING:
    from .connection import MyBackendConnectionManager

class MyBackendVectorProvider:
    """MyBackend implementation of VectorStorageProtocol."""

    SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset({"vector"})

    def __init__(self, connection_manager: "MyBackendConnectionManager") -> None:
        self._connection_manager = connection_manager

    @property
    def is_initialized(self) -> bool:
        return self._connection_manager.is_initialized

    async def upsert_chunks(self, chunks, project_id) -> int:
        # Implementation...
        pass

    async def vector_search(self, query_vector, limit, ...) -> List[SearchResult]:
        # Implementation...
        pass
```

### Step 4: Create Package Exports

```python
# mybackend/__init__.py
from .connection import MyBackendConnectionManager
from .vector import MyBackendVectorProvider

__all__ = [
    "MyBackendConnectionManager",
    "MyBackendVectorProvider",
]
```

### Step 5: Register in the Registry

```python
# In agent_vault/storage/registry.py

PROVIDER_REGISTRY["mybackend"] = {
    "vector": ("agent_vault.storage.providers.mybackend", "MyBackendVectorProvider"),
}
```

### Step 6: Add Configuration Support

Update `config/config.schema.json` to include your backend's configuration options.

## Backward Compatibility

When refactoring existing single-file providers into modules, maintain backward compatibility:

```python
# mybackend/__init__.py

# Re-export for backward compatibility
from .vector import MyBackendVectorProvider

# Legacy alias (if old code used a different name)
MyBackendProvider = MyBackendVectorProvider
```

## Directory Creation

**Important**: Backends own their directory creation. Do NOT rely on `config.ensure_storage_directories()`.

```python
# In connection manager's initialize() method:
async def initialize(self) -> None:
    # Backend creates its own directories
    storage_path = self._config.storage.get_mybackend_path()
    storage_path.mkdir(parents=True, exist_ok=True)
```

This follows the "inversion of responsibility" principle where agv core provides configuration context, but each backend manages its own resources.

## Testing

Create tests for:

1. **Lifecycle compliance**: `test_lifecycle_protocol.py`
2. **Protocol implementation**: Verify all protocol methods work
3. **Integration**: End-to-end with real backend

```python
@pytest.mark.asyncio
async def test_provider_lifecycle():
    config = create_test_config()
    manager = MyBackendConnectionManager.from_config(config, "test-project")

    # Not initialized yet
    assert not manager.is_initialized

    # Initialize
    await manager.initialize()
    assert manager.is_initialized

    # Health check
    health = await manager.health_check()
    assert health["healthy"] is True

    # Close
    await manager.close()
    assert not manager.is_initialized
```

---

## Unified PostgreSQL Provider and Adapters

Agent-Vault uses a unified PostgreSQL provider architecture that supports multiple cloud backends (GCP, AWS, Azure) through a pluggable adapter pattern.

### Architecture

**Single provider, multiple adapters:**
- **`PostgresVectorProvider`**: Generic vector storage logic using `pgvector`.
- **`PostgresGraphProvider`**: Generic graph storage logic using adjacency lists.
- **`PostgreSQLAdapter`**: Interface for cloud-specific SQL syntax and extensions.

**Available Adapters:**
- **`DefaultPostgresAdapter`**: Standard PostgreSQL (Local/Docker).
- **`AlloyDBAdapter`**: Google Cloud AlloyDB (uses `google_ml_integration`).
- **`RDSAdapter`**: AWS RDS/Aurora (uses `aws_ml` and Bedrock).
- **`AzurePostgresAdapter`**: Azure Database for PostgreSQL (uses `azure_ai`).

### Configuration-Driven Adapters

The provider automatically selects the correct adapter based on the `type` field in the backend configuration:

```yaml
# GCP AlloyDB
type: alloydb
embedding_strategy: server_side

# AWS RDS
type: rds
embedding_strategy: server_side

# Azure
type: azure
embedding_strategy: server_side
```

### Registry Mapping

The registry maps all PostgreSQL-compatible backends to the unified provider classes:

```python
# In agent_vault/storage/registry.py
PROVIDER_REGISTRY = {
    "postgresql": {
        "vector": ("...postgresql", "PostgresVectorProvider"),
        "graph": ("...postgresql", "PostgresGraphProvider"),
    },
    "alloydb": {
        "vector": ("...postgresql", "PostgresVectorProvider"),
        "graph": ("...postgresql", "PostgresGraphProvider"),
    },
    "rds": {
        "vector": ("...postgresql", "PostgresVectorProvider"),
        "graph": ("...postgresql", "PostgresGraphProvider"),
    },
    "azure": {
        "vector": ("...postgresql", "PostgresVectorProvider"),
        "graph": ("...postgresql", "PostgresGraphProvider"),
    },
}
```

### Server-Side Embedding Pattern

When `embedding_strategy="server_side"` is enabled, the provider delegates SQL generation to the adapter:

**1. SQL Generation:**
The adapter provides the specific function call for the platform:
- AlloyDB: `embedding('model', content)::vector`
- RDS: `agv_embed(content, 'model')::vector`
- Azure: `azure_ai.generate_embeddings('model', content)::vector`

**2. Optimized Search:**
The provider uses a **CTE (Common Table Expression)** to ensure the server-side embedding function is only called once per search query, improving performance and reducing API costs.

### Dead Code Note

The original `agent_vault/storage/providers/alloydb/` and `agent_vault/storage/providers/rds/` runtime provider files have been removed. 
- **Active**: `storage/providers/postgresql/` contains all runtime logic.
- **Active**: `cli/setup/` contains the provisioning wizards for each cloud.

### Migration Path

To add support for a new PostgreSQL-compatible cloud provider:
1. Create a new subclass of `PostgreSQLAdapter` in `adapter.py`.
2. Implement `get_embedding_sql()` and `required_extensions`.
3. Register the new type in `PostgresVectorProvider.from_config()` and `PostgresGraphProvider.from_config()`.
4. Add a new setup wizard in `agent_vault/cli/setup/`.

---

## Reference Implementations

- **LanceDB**: `agent_vault/storage/providers/lancedb/` - Local embedded database
- **PostgreSQL**: `agent_vault/storage/providers/postgresql/` - Unified provider for CloudSQL and AlloyDB
- **Memory**: `agent_vault/storage/providers/memory.py` - Simple in-memory for testing
- **AlloyDB (deprecated)**: `agent_vault/storage/providers/alloydb/` - Dead code, replaced by unified PostgreSQL provider
