# Ownership & Extension Points

This document is a guardrail for the database abstraction + connector architecture work. It answers:
- who owns query building and query semantics
- where reranking lives (and how to swap it)
- how schemas/queries differ per backend without forking app logic
- what an engineer must implement to add a new adapter/connector

## Ownership Boundaries (Normative)

### User Interface Layer (Plugin Skills + CLI + MCP)

Owns **user interaction and command orchestration**:
- **Plugin Skills** (PRIMARY): Claude Code plugin skills in `extensions/claude/agv/` and `extensions/claude/agv-dev/`
  - `/agv:search`, `/agv:index`, `/agv:onboard`, `/agv:entity`, etc.
  - Hook into Claude Code lifecycle (before/after build, etc.)
  - User-facing commands and workflows
  - `.github/` and `.codex/` mirrors point to the same skill and agent tree for Copilot and Codex
- **CLI** (SECONDARY): Command-line interface (`agv index`, `agv search`, etc.)
  - Batch operations, scripting, CI/CD integration
- **MCP** (ADVANCED/OPTIONAL): Model Context Protocol server for external integrations
  - Programmatic access for non-Claude AI clients

Non-goal: UI layer should not implement search/indexing logic directly—delegate to services.

### App Layer (SearchService + callers)

Owns **intent and orchestration**:
- Builds `QuerySpec` (what table(s), what filters, which retrieval modes, limits/offsets).
- Chooses retrieval strategy and fallbacks:
  - e.g. if adapter lacks native hybrid, run `vector_search` + `fts_search` and merge via reranker.
- Applies post-processing that is **not storage-primitive**:
  - deduplication
  - boosting (overview bias, recency boosts, etc.)
  - reranking (RRF, linear combination, cross-encoder, graph-based boosts)
- Produces the canonical `SearchResult` contract returned to consumers.

Non-goal: the app layer should not write backend-specific filter strings (SQL, DSL) or depend on backend-specific result shapes.

### Provider Layer (VectorStorageProtocol + GraphStorageProtocol + capabilities)

Owns **translation and execution**:
- Translates backend-agnostic `Filter` AST → backend-native filter/query representation.
- Maps logical schemas → physical schemas (column names/types/index config).
- Executes CRUD and query primitives used across the codebase (graph queries, cross-project queries, etc.).
- Returns enough raw fields to allow app-layer scoring/reranking (e.g. distance, matched text fields) without inventing new "result types".
- Handles embedding strategy differences (local vs. server-side embedding).
- Exposes `capabilities` property (not global lookup) for runtime behavior detection.

Non-goals:
- Do not embed business-level ranking semantics (boosting rules, "overview first", cross-encoder selection).
- Do not silently degrade "hybrid" requests by only executing one side. Either support native hybrid or raise a clear unsupported-capability error so the app layer can run the fallback plan.

**Architecture:**
- **StorageFacade** (`storage/facade.py`) provides unified entry point to all providers
- **Registry-based loading** (`storage/registry.py`): Maps backend type + role → provider class
- **Unified PostgreSQL Provider** (`storage/providers/postgresql/`): Single codebase handles PostgreSQL, CloudSQL, and AlloyDB
- **Embedding Strategy** (`BackendConfig.embedding_strategy`):
  - `"local"`: Generate embeddings client-side (SentenceTransformer), store as vectors
  - `"server_side"`: Skip embedding in upsert (NULL), call `generate_embeddings()` to populate via DB function
- **Auto-configuration**: `BackendConfig.validate_alloydb_config()` auto-sets server-side strategy for AlloyDB
- Providers instantiated via `StorageFacade.from_config()` or `registry.create_provider()`

**Registry Example:**
```python
PROVIDER_REGISTRY = {
    "postgresql": {"vector": ("...postgresql", "PostgresVectorProvider"), ...},
    "alloydb": {"vector": ("...postgresql", "PostgresVectorProvider"), ...},  # Same provider
    "lancedb": {"vector": ("...lancedb", "LanceDBProvider"), ...},
}
```

### Reranker Layer (RerankerProtocol)

Owns **post-retrieval ordering**:
- Accepts/returns `list[SearchResult]`.
- May use model inference (cross-encoder/ColBERT) or heuristics (RRF).
- Must preserve identity (same `SearchResult.id`) and re-normalize `score` to `[0.0, 1.0]`.

Non-goals:
- Do not reach into the adapter to fetch more rows mid-rerank. If more candidates are required, the app layer adjusts `QuerySpec` and refetches.

### Connector Layer (ConnectorProtocol)

Owns **source enumeration and content retrieval**:
- Lists `SourceItem` units under a root.
- Opens content into `SourceContent` (bytes + metadata).
- Manages source-specific change detection and (for remote sources) local materialization for path-based parsers.

Non-goals:
- Do not parse or chunk content.
- Do not own database persistence.

---

## Schema & Query Differences Across Backends

### Logical vs Physical Schema

- The app layer speaks **logical schemas** only (see `docs/design/logical-schema-reference.md`).
- Each adapter implements logical→physical mapping:
  - physical column names/types/indexes can differ
  - adapters may ignore unsupported columns, but must document behavior

### Backend Feature Differences

- Feature differences are expressed through **capabilities**, not conditional logic sprinkled throughout the app.
- If an adapter cannot satisfy a `QuerySpec` requirement, it must raise a clear error indicating which capability is missing.
- The app layer owns the fallback plan (e.g. emulate offset, split query into two passes, or disable a feature).

---

## “Who Owns Query Building?”

**Canonical rule:** The app owns “what we want”; the adapter owns “how to execute it”.

Concrete responsibilities:
- App builds a `QuerySpec` and chooses whether to call:
  - `adapter.query(...)` (table + filters)
  - `adapter.vector_search(...)` / `adapter.fts_search(...)`
  - native hybrid (if supported) or app-layer hybrid plan + reranker
- Adapter translates the `Filter` AST and applies schema mapping.

---

## “Should Reranking Be an Adapter?”

Recommendation: **No.** Keep reranking as a separate pluggable component (`RerankerProtocol`) because:
- reranking semantics are product-level and frequently evolve
- some rerankers depend on ML inference, not storage backends
- it keeps adapters minimal and makes test compliance practical

Exception: If a storage backend provides a native hybrid+rerank primitive, it can be exposed as a capability, but the output must still be mapped into the canonical `SearchResult` boundary and must not prevent app-layer reranking overrides.

---

## What an Engineer Must Implement (Providers/Connectors)

### New Storage Provider

Minimum work:
- Implement `VectorStorageProtocol` and/or `GraphStorageProtocol` (see `agent_vault.storage.protocols`)
- Implement lifecycle methods: `initialize()`, `close()`, `health_check()`
- Implement CRUD methods: `upsert_chunks()`, `delete_chunks()`, `get_chunks()`
- Implement search methods: `vector_search()`, `fts_search()`, optionally `hybrid_search()`
- Implement embedding strategy support:
  - Local: accept pre-computed embeddings in upsert
  - Server-side: skip embedding column in upsert, implement `generate_embeddings()`
- Implement `Filter` AST translation with strict field validation
- Implement logical→physical schema mapping and index configuration
- Register provider in `agent_vault.storage.registry`
- Add config schema to `storage/schemas/<backend>.schema.json`
- Pass protocol compliance tests

### Example: Unified PostgreSQL Provider

The PostgreSQL provider (`storage/providers/postgresql/`) demonstrates multi-backend support:

**Single codebase, multiple backends:**
- Handles PostgreSQL, CloudSQL, and AlloyDB via same provider classes
- Registry maps all three backend types to `PostgresVectorProvider`, `PostgresGraphProvider`, etc.

**Configuration-driven behavior:**
- `embedding_strategy` field on `BackendConfig`: `"local"` or `"server_side"`
- `validate_alloydb_config()` model validator auto-sets `server_side` + `text-embedding-005` + 768 dims for AlloyDB
- Provider checks `self._config.embedding_strategy` at runtime to branch behavior

**Key methods:**
- `from_config()`: Builds DSN from config (handles direct connection or GCP proxy params)
- `initialize()`: Installs `google_ml_integration` extension for server-side mode
- `upsert_chunks()`: Skips embedding column for server-side (inserts NULL)
- `vector_search()`: Accepts `str` for server-side (passes to `ai.embedding()`), `List[float]` for local
- `generate_embeddings()`: Server-side only—populates NULL embeddings via `ai.initialize_embeddings()` or per-row fallback

**Capabilities:**
- Provider exposes `capabilities` property returning `ALLOYDB_CAPABILITIES` or `POSTGRESQL_CAPABILITIES`
- Not a global lookup—each provider instance knows its own capabilities based on config

### New Connector

Minimum work:
- Implement `ConnectorProtocol.list()` and `.open()`.
- Provide stable `SourceItem.uri` and change detection fields.
- If remote: implement deterministic local materialization (until content-based parsing exists).
- Ensure connector metadata is JSON-serializable and safe for persistence/logging.
- Add config wiring + tests for enumerate/open/materialize.

### Custom Reranker

Minimum work:
- Implement `RerankerProtocol.rerank(results, context=...) -> list[SearchResult]` (exact signature per spec).
- Re-normalize scores to `[0.0, 1.0]` and preserve `id`.
- Register via registry mechanism and document configuration.
