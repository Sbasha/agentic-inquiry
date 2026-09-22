# Storage providers and the external provider contract

Agentic Inquiry stores everything locally. This page states which providers ship, how storage roles are assigned to them, and the contract an external database provider for governed projects must satisfy. No external provider ships in this distribution; the contract is documented so that design work can start from the real interface rather than from a description of it.

## Shipped providers

| Role | Provider | Type | Notes |
|------|----------|------|-------|
| `vector` | LanceDB | `lancedb` | Chunks, embeddings, full-text search |
| `graph` | LanceDB | `lancedb` | Entities and relationships |
| `events` | SQLite | `sqlite` | Operation and audit events |
| `file_tracker` | SQLite | `sqlite` | File hashes for change detection |
| `onboard_metadata` | SQLite | `sqlite` | Onboarding run records |
| any | In-memory | `memory` | Tests and throwaway sessions; nothing persists |

Roles are assigned in `storage` configuration. Named backends with explicit role assignments:

```yaml
storage:
  root: "/data/agentic-inquiry"
  backends:
    default:
      type: lancedb
      uri: "${storage.root}/lancedb"
    local_sqlite:
      type: sqlite
      path: "${storage.root}/local.db"
  vector_backend: default
  graph_backend: default
  events_backend: local_sqlite
  file_tracker_backend_v2: local_sqlite
```

The single-provider form remains supported:

```yaml
storage:
  root: "/data/agentic-inquiry"
  lancedb:
    uri: "${storage.root}/lancedb"
```

The registry in `agentic_inquiry/storage/registry.py` maps `(backend type, role)` to a provider class. `StorageFacade` (`agentic_inquiry/storage/facade.py`) resolves each role once, owns provider lifecycle and exposes one API to indexing, search, memory and the MCP server. Consumers query `ProviderCapabilities` (`agentic_inquiry/storage/capabilities.py`) instead of testing backend type strings.

## The provider contract

A provider is a class that implements one or more of the protocols in `agentic_inquiry/storage/protocols/`. The protocols are `typing.Protocol` classes; a provider satisfies them structurally and does not need to inherit from anything, although `agentic_inquiry/storage/providers/base.py` offers `BaseProvider` with lifecycle guards and `MaintenanceMixin` with default maintenance operations.

| Protocol | File | Responsibility | Required operations |
|----------|------|----------------|---------------------|
| `BackendLifecycle` | `lifecycle.py` | Construction and lifetime | `from_config(config, project_id)`, `initialize()`, `close()`, `health_check()`, `is_initialized` |
| `VectorStorageProtocol` | `vector.py` | Chunk storage and retrieval | `upsert_chunks`, `delete_chunks_by_file`, `delete_chunks_by_ids`, `get_chunks_by_file`, `vector_search`, `fts_search`, `hybrid_search`, `query`, `count`, `entity_vector_search`, `query_across_projects`, `list_tables`, `table_exists` |
| `GraphStorageProtocol` | `graph.py` | Entities and relationships | `upsert_entities`, `get_entity`, `get_entities_by_file`, `get_entities_by_type`, `delete_entities_by_file`, `delete_entities_by_ids`, `query_entities`, `count_entities`, `upsert_relationships`, `get_relationships_by_entity`, `delete_relationships_by_file`, `delete_relationships_by_entity`, `delete_relationships_by_ids`, `query_relationships`, `count_relationships_by_type`, `get_neighbors`, `traverse` |
| `EventStorageProtocol` | `events.py` | Operation events | `write_events`, `query_events`, `get_operation_events`, `get_operation_status`, `count_events`, `delete_before`, `run_maintenance` |
| `FileTrackerProtocol` | `file_tracker.py` | Change detection | `get_hash`, `update_hash`, `has_changed`, `remove_file`, `list_tracked_files`, `clear`, plus the synchronous variants |
| `IndexingStorageProtocol` | `indexing.py` | Bulk writes during indexing | `add_document_chunks`, `delete_document_chunks`, `add_graph_entities`, `delete_graph_entities`, `add_graph_relationships`, `delete_graph_relationships`, `advanced_filter`, `query_entities`, `run_maintenance` |
| `MaintenanceProtocol` | `vector.py` | Health and repair | `health_check`, `run_maintenance`, `compact`, `validate_integrity`, `cleanup_orphaned_data` |
| `TransactionProtocol`, `TransactionContext` | `vector.py` | Coordinated multi-table writes | `begin_transaction`, `commit`, `rollback`; the context batches operations and `flush`es them |
| `TransactionAwareProvider` | `transaction.py` | Sharing one connection across providers inside a transaction | `set_transaction_connection`, `clear_transaction_connection`, `in_transaction` |

Every read and write is scoped by `project_id`. Filters arrive as the filter AST in `agentic_inquiry/database/filters/` and each provider translates the AST to its own query language; a provider must reject fields and operators it does not know rather than interpolate them. Similarity metrics are declared through `BackendConfig.similarity_metric` and translated by `agentic_inquiry/storage/similarity.py`.

The local providers commit per operation. `StorageFacade.transaction()` raises `TransactionError` for them; an external provider that implements `TransactionProtocol` and `TransactionAwareProvider` gets coordinated vector and graph writes through the same facade call.

## What an external provider for governed projects must add

The contract above is what the runtime needs. A governed deployment needs the following on top, and none of it exists in the local providers:

- **Identity and tenancy.** `project_id` is the only scope the runtime passes. A governed provider must map it to an owning principal or tenant and refuse cross-project reads and writes at the database, not only in the facade. `query_across_projects` must be restricted to explicitly shared projects.
- **Authentication.** Providers receive `BackendConfig` (`agentic_inquiry/storage/config.py`). Credentials must come from the environment or a secret store the operator controls; nothing in the runtime persists them.
- **Audit.** `EventStorageProtocol` is the audit surface. A governed provider must make events append-only and attributable, and must not let `delete_before` erase records inside a retention window.
- **Embedding placement.** `ProviderCapabilities.embedding_strategy` declares whether vectors are produced locally or by the database. A server-side strategy changes dimensions and the indexing pipeline's expectations; the pipeline calls `generate_embeddings()` hooks that are no-ops for local providers.
- **Schema evolution and backup.** The runtime assumes a provider owns its schema. A governed provider needs versioned schema migration, backup and restore paths that keep durable records and knowledge intact; the local backup command in `agentic_inquiry/library.py` is the behavioural reference.
- **Capabilities.** Register the provider in `PROVIDER_REGISTRY` and add a `ProviderCapabilities` entry; consumers rely on that entry for feature detection.

Implementation guidance for the adapter layer is in [docs/development/adapter-implementation-guide.md](development/adapter-implementation-guide.md) and [docs/architecture/storage-adapters.md](architecture/storage-adapters.md). Both describe the earlier PostgreSQL-family reference implementation, which is not part of this distribution; read them as design input, not as a description of shipped code.
