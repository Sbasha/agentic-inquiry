# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **GCS content source is now actually usable** (#82). `GCSConnector`
  carried `@register_connector("gcs")` but nothing imported its module at
  runtime, so the decorator never fired — `get_connector("gcs", ...)` raised
  `KeyError` and `"gcs"` never appeared in `list_connectors()`, despite GCS
  being documented as a first-class source. It is now registered at import
  time (guarded on `gcsfs`, like S3). The GCS URI scheme was also aligned
  from `gs://` to `gcs://` to match the registered connector name,
  `SourceItem.protocol`, and the connector guide. `GCSConnector` is now
  exported from `agent-vault.connectors`. Install with
  `pip install agent-vault[gcs]`.

### Changed (potentially breaking)

- **`PostgreSQLAdapter.required_extensions` is now a method** (#159).
  Previously a `@property` returning every extension unconditionally;
  now `required_extensions(embedding_strategy: str = "local") -> list[str]`
  so that the cloud-specific ML extensions (`aws_ml`, `azure_ai`,
  `google_ml_integration`) are only requested on the SERVER_SIDE
  path. This fixes the long-standing bug where plain RDS for
  PostgreSQL with `embedding_strategy: local` would fail at
  `CREATE EXTENSION aws_ml` (Aurora-only). Internal call sites
  (`PostgresVectorProvider.initialize`, `PostgresGraphProvider.initialize`,
  `AzureSetup._verify_and_initialize`) updated. Custom adapters
  living outside this repo that override `required_extensions` need
  to switch from `@property` to `def required_extensions(self,
  embedding_strategy: str = "local") -> list[str]:`. Pre-1.0, no
  external consumers known.

### Removed

- **Speculative cognitive-architecture modules** (#157). Deleted
  `agent-vault/executive/` (VolitionEngine, ExecutiveLoop, SelfAuditService,
  ExecutiveTriggers), `agent-vault/simulation/` (SimulationEngine and the
  `simulate_change` MCP tool), `agent-vault/learning/` (LearningCapture,
  zero non-test importers), and `agent-vault/ui/` (NiceGUI dashboard with
  hardcoded placeholder values). Removed `nicegui` and `plotly` from runtime
  dependencies. Removed the `agv ui` CLI subcommand. The `executive_loop`
  was replaced by a 25-line periodic maintenance task in `mcp/factories.py`
  that calls `memory_system.consolidate()` and `storage.run_maintenance()`
  every 60 seconds (work-first, then sleep).

### Changed

- **`GET /health` response shape** (#157). The endpoint no longer returns the
  `executive_loop`, `self_audit`, or `volition_engine` keys (those services
  no longer exist). It now returns a single `maintenance_task: {running: bool}`
  field in their place. `status`, `components`, `is_active`, and `performance`
  keys are unchanged. Any dashboard scraping the executive-function keys must
  migrate.
- **Plugin manifest versions resynced to `1.5.0`** (#158, #170). Five different
  version numbers were claimed across the repo (pyproject `1.5.0`, claude
  plugins `2.1.0`, gemini plugins `1.5.1`, README `1.4.0` in two places).
  All plugin manifests (claude/agv, claude/agv-dev, gemini/agv,
  gemini/agv-dev) are now `1.5.0`, matching `pyproject.toml`. Note: this
  is a numerical *downgrade* for the claude plugins (`2.1.0` → `1.5.0`).
  The `2.1.0` value was internally inconsistent and almost certainly an
  unintended edit; if any plugin manager keys on monotonic versions, you
  may need to manually re-pin `agv@1.5.0` rather than auto-update.

### Added

- **Configurable similarity metric** for vector indexes. New `similarity_metric`
  field on `BackendConfig` accepts the canonical names `cosine` (default),
  `l2`, and `dot`. A new `agent-vault.storage.similarity` module translates
  these to each backend's native spelling (LanceDB `cosine`/`l2`/`dot`,
  pgvector `vector_cosine_ops` / `<=>`, OpenSearch `cosinesimil`, etc.).
- `LanceDBManager`, `TableManager`, and `LanceDBSchemaManager` now accept a
  `similarity_metric` kwarg and thread it into `create_index(metric=...)`.
  `LanceDBManager.from_config` picks the value up from the active named-backend
  config when present.

### Changed

- LanceDB vector index creation no longer hardcodes `metric="cosine"` — the
  metric is read from config. Default remains `cosine`, so existing
  deployments are unaffected.
- `similarity_metric` is now honoured end-to-end on the unified pgvector
  provider (`postgresql`, `cloudsql`, `alloydb`, `rds`). `PostgresConnectionManager`
  carries the metric and `PostgresVectorProvider` / `PostgresGraphProvider`
  use it to pick the correct pgvector distance operator (`<=>` / `<->` / `<#>`)
  at query time and the matching operator class (`vector_cosine_ops` /
  `vector_l2_ops` / `vector_ip_ops`) at index creation time.
- `SchemaGenerator` (and `AlloyDBSchemaGenerator`) accept `similarity_metric`
  and inject the resolved op-class via a new `{vector_op_class}` placeholder
  in static index templates — preserving existing DDL when the default is used.
- `BackendConfig.validate_similarity_metric` no longer rejects non-cosine
  values on pgvector-based backends now that the runtime path honours the
  configured metric.
- PostgreSQL vector search result scoring is now metric-aware. Queries select
  the raw pgvector distance and `_row_to_search_result` converts it into a
  `[0, 1]` similarity via a new `distance_to_similarity(distance, metric)`
  helper. The previous `1 - distance` formula baked into SQL was only valid
  for cosine; for `l2` it underflowed to `0` for typical Euclidean distances,
  and for `dot` it over-clamped when vectors weren't normalized. The unused
  `similarity` column was dropped from `entity_vector_search` queries in the
  graph provider — only `_distance` was consumed downstream.
- `PostgresMaintenanceService.rebuild_index` now reads `similarity_metric`
  from its `PostgresConnectionManager` and passes it to `SchemaGenerator`.
  Previously it instantiated `SchemaGenerator()` with no arguments, so any
  rebuild against an l2/dot-configured database silently emitted
  `vector_cosine_ops` into the new index. Both CLI callers
  (`agv index migrate`, `agv maintenance`) now thread the metric through:
  `cli/index_migrate.py` gains a `--similarity-metric` option (default
  `cosine`), and `cli/maintenance.py` builds the connection manager via
  `PostgresConnectionManager.from_backend_config(...)` so a
  `BackendConfig.similarity_metric` flows into rebuild DDL automatically.

## [1.0.0] - 2026-01-04

### Breaking Changes

- **Named Backend Configuration**: StorageConfig now supports named backends with role assignments
  - New `backends` dict maps backend names to BackendConfig objects
  - Role assignment fields (`vector_backend`, `graph_backend`, `events_backend`, `file_tracker_backend_v2`) reference backend names
  - Legacy configuration fields (`backend`, `event_store_backend`, `file_tracker_backend`) remain for backward compatibility
  - **Migration**: Update configuration to use new named backends format:
    ```yaml
    # New format (recommended):
    storage:
      backends:
        primary:
          type: postgresql
          connection_string: postgres://localhost/db
        local:
          type: sqlite
          database_path: ./data/agent-vault.db
      vector_backend: primary
      graph_backend: primary
      events_backend: local
      file_tracker_backend_v2: local

    # Legacy format (still supported):
    storage:
      backend: lancedb
      event_store_backend: sqlite
      file_tracker_backend: sqlite
    ```

- **New Storage Protocols**: Added EventStorageProtocol and FileTrackerProtocol
  - `EventStorageProtocol`: 9 methods for event persistence abstraction
  - `FileTrackerProtocol`: 14 methods (async + sync wrappers for watchdog)
  - Both protocols use `@runtime_checkable` for structural typing

- **StorageFacade Constructor**: Now accepts 4 providers + pool manager
  - `vector_provider`: VectorStorageProtocol
  - `graph_provider`: GraphStorageProtocol
  - `events_provider`: Optional[EventStorageProtocol]
  - `file_tracker_provider`: Optional[FileTrackerProtocol]
  - `pool_manager`: Optional[BackendPoolManager]

### Added

- **PostgreSQL Providers**: Full PostgreSQL backend with pgvector extension
  - `PostgresVectorProvider`: Vector storage (14 methods) with pgvector similarity search
  - `PostgresGraphProvider`: Graph storage (16+ methods) using adjacency tables
  - `PostgresEventProvider`: Event logging (9 methods) with JSONB storage
  - `PostgresFileTrackerProvider`: File tracking (14 methods) with sync wrappers
  - `PostgresConnectionManager`: Shared asyncpg connection pool management
  - Table prefix convention: `agv_v_`, `agv_g_`, `agv_e_`, `agv_f_` for role isolation
  - Requires: `pip install agent-vault[postgresql]`

- **SQLite Providers**: Protocol-compliant SQLite storage
  - `SQLiteEventProvider`: Extends existing SQLiteEventStorage with protocol compliance
  - `SQLiteFileTrackerProvider`: Extends FileTracker with protocol compliance and sync wrappers
  - Both providers include `SUPPORTED_ROLES` class attribute

- **BackendConfig** (pydantic model): Validated configuration for storage backends
  - Type-dependent field validation (connection_string for PostgreSQL, database_path for SQLite/LanceDB)
  - Pool settings (pool_size, max_overflow) for connection-pooled backends
  - Spanner-specific fields (project_id, instance_id, database_id)

- **BackendRegistry**: Lazy-loading registry for storage provider classes
  - Maps backend types (lancedb, postgresql, sqlite, spanner, memory) to provider classes
  - Role-based provider lookup (vector, graph, events, file_tracker)
  - `get_provider_class()`: Lazy-load and cache provider classes
  - `resolve_backend()`: Resolve role to backend name and configuration
  - `create_provider()`: Convenience function to instantiate providers

- **BackendPoolManager**: Connection pool management for backends
  - Singleton pool per backend name
  - PostgreSQL connection pooling via asyncpg
  - Path references for file-based backends (SQLite, LanceDB)
  - Graceful shutdown with `close_all()`

- **StorageFacade Properties**:
  - `events_provider`: Access to events storage provider
  - `file_tracker_provider`: Access to file tracker provider
  - `pool_manager`: Access to connection pool manager

- **Testing Infrastructure**:
  - `docker-compose.dev.yaml`: Local PostgreSQL (pgvector/pgvector:0.8.1-pg16)
  - New pytest markers: `@pytest.mark.postgres`, `@pytest.mark.spanner`
  - Integration test fixtures for PostgreSQL providers
  - 21 new StorageFacade unit tests

- **Documentation**:
  - `docs/storage-backends.md`: Comprehensive guide for pluggable backends

### Changed

- **StorageConfig**: Extended with optional `backends` dict and role assignment fields
  - New field: `backends: Optional[Dict[str, Dict[str, Any]]]`
  - New fields: `vector_backend`, `graph_backend`, `events_backend`, `file_tracker_backend_v2`
  - New field: `table_prefix` for schema isolation

- **StorageFacade.from_config()**: Uses registry when backends configured, legacy mode otherwise

- **StorageFacade.run_maintenance()**: Delegates to all providers' `run_maintenance()` methods

- **StorageFacade.initialize/close()**: Handle all provider types, deduplicate shared providers

### Deprecated

- `StorageFacade.count_records()`: Use `count_chunks()` or `provider.count()` directly
- `StorageFacade.advanced_filter()`: Use `provider.query()` directly

### Deferred

- **Spanner Provider** (Phase 5): Deferred to v2 due to:
  - `google-cloud-spanner` SDK is synchronous-only (no native async support)
  - GQL quantifier bounds require integer literals (can't use parameters)
  - High operational cost compared to PostgreSQL

---

### Breaking Changes (from previous unreleased)

- **Configuration Validation**: Invalid ranking weights are now rejected instead of being silently normalized
  - The configuration system now raises `ConfigurationError` when memory retrieval ranking weights do not sum to 1.0 (±0.01)
  - Previously, invalid weights were automatically normalized with a warning, which could hide configuration errors
  - **Migration**: Review your configuration files and ensure ranking weights sum to 1.0:
    ```yaml
    # Before (was silently normalized):
    memory:
      retrieval:
        ranking_weights:
          relevance: 0.5
          recency: 0.5
          importance: 0.5  # Sum = 1.5, was normalized
    
    # After (must be fixed):
    memory:
      retrieval:
        ranking_weights:
          relevance: 0.4
          recency: 0.4
          importance: 0.2  # Sum = 1.0 ✓
    ```
  - Error message will indicate the current sum and provide guidance on fixing the configuration
  - This change ensures configuration errors are caught early rather than causing unexpected runtime behavior

### Fixed

- **Relationship Collection in Indexing Pipeline**: Fixed missing relationship collection during document processing
  - Relationships from parsed chunks are now properly collected in `_pending_relationships`
  - Import frequency tracking now works correctly for symbol resolution
  - Document structure and code dependencies are properly represented in the graph database
  - Fixes 3 test failures: `test_document_entity_integration`, `test_document_entity_registration`, `test_two_pass_resolution`

- **Async Coroutine Execution**: Fixed unawaited coroutines in examples and file watcher
  - `ParserChain.parse()` calls in examples now properly awaited
  - `FileTracker.update_hash()` and `FileTracker.remove_file()` in file watcher now properly awaited
  - Eliminated 6 RuntimeWarning messages about unawaited coroutines
  - Examples now demonstrate correct async usage patterns

- **Pytest Configuration**: Added proper marker registration to eliminate warnings
  - Registered "slow" marker in pytest configuration
  - Eliminated PytestUnknownMarkWarning messages
  - Test categorization now works without warnings

- **Cache Behavior**: Fixed cache being used when explicitly disabled
  - RetrievalEngine now respects `cache_enabled=False` configuration
  - Cache statistics now accurately reflect actual cache usage
  - Fixes test failure: `test_retrieve_with_disabled_cache`

- **Memory System Configuration**: Memory tiers now properly respect configured capacity values
  - Fixed issue where memory system components might ignore configuration values
  - Working memory, episodic memory, and semantic memory now correctly use capacity values from configuration
  - Tests now verify that configuration values are actually applied to the memory system

- **Test Suite Integrity**: Restored proper test assertions that were weakened during async migration
  - Configuration validation tests now properly verify that invalid configs are rejected
  - Memory system tests now verify actual behavior rather than just checking configuration values
  - Feedback storage tests now verify that feedback content is properly stored and retrievable
  - These fixes ensure the test suite catches real regressions

### Clarified

- **Batch Store API**: Clarified that `MemorySystem.batch_store()` uses tuple-based API
  - The method signature has always been tuple-based: `(content, context, importance, summary, metadata)`
  - Added docstring examples showing correct usage
  - Example:
    ```python
    # Correct API usage:
    items = [
        ("Event 1", context, 0.7, "Summary 1", None),
        ("Event 2", context, 0.8, "Summary 2", None),
    ]
    await memory_system.batch_store(items=items)
    ```
  - This is not a breaking change - the API has always been tuple-based, but documentation has been improved

### Added

- **Local Model Embedder**: New `LocalModelEmbedder` class for using locally-stored ONNX models
  - Enables completely offline operation without external API dependencies
  - Supports ONNX format models with optimized inference
  - Includes workspace-aware model storage and loading
  - Provides async embedding generation for non-blocking operations
  - Implements batch processing with configurable batch sizes
  - Supports embedding normalization for cosine similarity search

- **Model Conversion Script**: New `scripts/convert_model.py` utility
  - Downloads models from HuggingFace Hub
  - Converts models to ONNX format for optimized inference
  - Extracts and saves tokenizer configuration
  - Generates model metadata with dimensions and settings
  - Supports quantization for smaller model sizes (experimental)
  - Validates converted models before saving

- **Model Management Components**:
  - `ModelLoader` class for loading and caching ONNX models
  - `ModelMetadata` dataclass for storing model configuration
  - Automatic model format detection (ONNX, safetensors, PyTorch)
  - Model caching to avoid repeated loading

- **Configuration Support**:
  - New `embeddings.local_model` configuration section
  - Environment variable overrides with `AGV_` prefix
  - Workspace-relative and absolute path support
  - Configurable batch size and normalization settings

- **Documentation**:
  - Comprehensive user guide at `docs/guides/local-models.md`
  - Model conversion guide at `docs/guides/model-conversion.md`
  - API reference documentation at `docs/api-reference/embeddings.md`
  - Updated architecture documentation with local model integration

- **Examples**:
  - Basic local model usage example
  - Model conversion example
  - Advanced configuration example
  - Integration with indexing pipeline

- **Tests**:
  - Comprehensive unit tests for `LocalModelEmbedder`
  - Unit tests for `ModelLoader` and `ModelMetadata`
  - Integration tests with `EmbeddingRegistry`
  - Integration tests with indexing pipeline
  - Tests for model conversion script
  - Offline operation verification tests
  - Performance tests for different batch sizes

### Changed

- Updated `EmbeddingRegistry` to support local model embedder
- Enhanced factory functions to create embedders based on configuration
- Updated configuration schema to include local model settings

### Dependencies

- Added `onnxruntime` for ONNX model inference
- Added `tokenizers` for fast tokenization
- Added `optimum` as dev dependency for model conversion

## [Previous Releases]

See git history for previous changes.
