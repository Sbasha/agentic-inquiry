# PostgreSQL Provider (pg-family)

Serves **five** backend-type strings: `postgresql`, `cloudsql`, `alloydb`, `rds`, `azure`. All five route through the same provider classes and differentiate via the adapter pattern. This is the production-leaning path.

Registry (`storage/registry.py`) maps these five types to the same module paths:
- vector → `PostgresVectorProvider`
- graph → `PostgresGraphProvider`
- events → `PostgresEventProvider`
- file_tracker → `PostgresFileTrackerProvider`
- onboard_metadata → `PostgresOnboardMetadataProvider` (in `agent_vault/onboard/providers/postgresql/`)

## File map

| File | Purpose |
|---|---|
| `adapter.py` | Dialect abstraction — `DefaultPostgresAdapter`, `AlloyDBAdapter`, `RDSAdapter`, `AzurePostgresAdapter`. Each overrides embedding-SQL generation and required extensions |
| `connection.py` | `PostgresConnectionManager` — asyncpg pool, health checks, `from_config` builds DSN from `connection_string` or cloud-specific fields |
| `vector.py` | `PostgresVectorProvider` — pgvector chunk storage + search. Dispatches on `type` to pick an adapter in `from_config` |
| `graph.py` | `PostgresGraphProvider` — adjacency-list entity/relationship storage |
| `events.py` | `PostgresEventProvider` — audit log; richer than the SQLite counterpart |
| `file_tracker.py` | `PostgresFileTrackerProvider` — SHA256 hash tracking with proper indexes |
| `transaction.py` | `TransactionCoordinator` — cross-provider atomic operations (shared connection injection) |
| `index_config.py` | `IndexConfig` + HNSW/IVFFlat parameter helpers. Exposes the knobs LanceDB doesn't |
| `migration.py` | Embedding-dimension migrations with backup-and-verify |
| `schemas.py` | DDL generation (table prefixes, HNSW/IVFFlat indexes) |
| `schema_tracker.py` | Tracks schema version / last-modified / embedding dim per table |
| `consistency.py` | Row-count + dim validation across roles |
| `maintenance.py` | Index rebuild (HNSW + IVFFlat), VACUUM, ANALYZE |
| `backup_cleanup.py` | Retention for migration backup tables |

Adjacent: `agent_vault/storage/providers/alloydb/` and `agent_vault/storage/providers/cloudsql/` — cloud-specific **connection managers** (IAM auth, proxy setup, `google_ml_integration` bootstrap). The runtime vector/graph/events providers all live here.

## Adapter system

`PostgresVectorProvider.from_config` reads `config["type"]` and picks an adapter:

| `type=` | Adapter | Extensions required | Server-side embedding? | Proxy |
|---|---|---|---|---|
| `postgresql` | `DefaultPostgresAdapter` | `vector` | no (raises `NotImplementedError`) | none |
| `cloudsql` | `DefaultPostgresAdapter(is_cloudsql=True)` | `vector` | no | `cloud-sql-proxy` |
| `alloydb` | `AlloyDBAdapter` | `vector`, `google_ml_integration` | **yes** — `embedding('{model}', content)::vector` | `alloydb-auth-proxy` |
| `rds` | `RDSAdapter` | `vector`, `aws_ml` | yes — `agv_embed(content, '{model}')::vector` (helper function wraps Bedrock) | none |
| `azure` | `AzurePostgresAdapter` | `vector`, `azure_ai` | yes — `azure_ai.generate_embeddings('{model}', content)::vector` | none |

When adding a new dialect, subclass `PostgreSQLAdapter` in `adapter.py` and extend the dispatch in `PostgresVectorProvider.from_config`. `PostgresGraphProvider.from_config` has the same dispatch for entity-embedding SQL.

## Config surface

| Config key | Default | Notes |
|---|---|---|
| `connection_string` | — | Required for `postgresql` / `rds` / `azure`. Cloud variants can build from host/port/db fields instead |
| `pool_size` | `5` for `alloydb`, `10` elsewhere | Default set on both dispatch paths: `AlloyDBConnectionManager.from_config` (primary vector/graph path — see `vector.py`/`graph.py` dispatch to `AlloyDBConnectionManager` for `type=alloydb`) and `PostgresConnectionManager.from_config` (events/file_tracker or fallback paths). AlloyDB small shares `max_connections=25` — defaulting to 5 leaves headroom for other workloads |
| `min_pool_size` | `2` | Always-on connections |
| `max_overflow` | `5` | `asyncpg.create_pool(max_size=pool_size + max_overflow)` |
| `command_timeout` | `60.0s` self-hosted, `900s` for `alloydb`/`cloudsql`/`rds`/`azure` | Configurable on **both** dispatch paths: `AlloyDBConnectionManager.from_config` reads it from the config dict (falling back to `DEFAULT_COMMAND_TIMEOUT=900.0` when absent), and `PostgresConnectionManager.from_config` falls back to the same 900s for the other cloud variants. AlloyDB used to hardcode 300s in `__init__`, silently dropping operator overrides — bumped and made configurable because `ai.initialize_embeddings` routinely exceeds 5 min on large tables. CloudSQL inherits the long default because it shares the AlloyDB-adjacent tooling flow even though it doesn't do server-side embedding itself |
| `similarity_metric` | `cosine` | Pinned at index build |
| `index_type` | `hnsw` | Also `ivfflat`, `none` |
| `index_params` | `{m:16, ef_construction:64}` for HNSW | Exposed via `IndexConfig` |
| `expected_rows` | `None` | Used to auto-size IVFFlat `lists = min(sqrt(n), 10000)` |
| `embedding_strategy` | `"local"` except AlloyDB defaults to `"server_side"` (`vector.py`) | Drives whether pipeline computes or defers embeddings |
| `embedding_model` | backend-specific | AlloyDB: `text-embedding-005`; RDS: Bedrock model ID; Azure: deployment name |
| `embedding_dim` | `384` local / `768` AlloyDB / `1024` RDS | Must match the model |
| `table_prefix` | `agv_` (`storage.table_prefix`) | Schema isolation for multi-tenant |
| `fts_language` | `english` | `tsvector` config |

## Defaults evaluation

**Sensible:**

- `pool_size` backend-aware default (`5` for AlloyDB, `10` elsewhere) — honest about AlloyDB small's `max_connections=25` ceiling while leaving headroom on self-hosted / RDS / Azure instances that typically have 100+ connections available.
- HNSW with `m=16, ef_construction=64` — recall-friendly without tuning, correct default.
- `command_timeout = 900s` covers every cloud-hosted variant (`alloydb`, `cloudsql`, `rds`, `azure`); three of those (`alloydb`/`rds`/`azure`) have genuinely slow server-side embedding paths, and `cloudsql` inherits the long default because it shares the AlloyDB-adjacent tooling flow. Self-hosted `postgresql` stays on 60s since there's no slow helper function in the default install.
- `embedding_strategy` auto-flipping to `server_side` for AlloyDB — matches the one backend where it materially changes indexing throughput.
- `table_prefix = agv_` — sensible for shared-DB multi-tenant patterns.

**Needs tuning:**

- **No per-variant default for Azure's `embedding_dim`.** Azure OpenAI's `text-embedding-3-small` is 1536 dims; falls back to `384` unless user sets it. Silently wrong for the common Azure configuration. Worth a follow-up that extends the alloydb-style auto-flip in `vector.py`.
- **IVFFlat `lists` can fall back to a hardcoded `100`** in `schemas.py` if `expected_rows` isn't set. For >100k rows this is quadratic in scan cost — always set `expected_rows` when using IVFFlat, or prefer HNSW.

**Genuinely wrong if left alone:**

- `embedding_strategy = "local"` on RDS with a working `agv_embed` helper installed — you're burning client CPU. Flip to `"server_side"`.
- `embedding_dim = 384` on *any* server-side backend. Server-side embedding models produce 768 / 1024 / 1536 dims; must match.

## Per-variant quick reference

| | postgresql | cloudsql | alloydb | rds | azure |
|---|---|---|---|---|---|
| Default `pool_size` | 10 | 10 | **5** | 10 | 10 |
| Default `command_timeout` | 60s | 900s | 900s | 900s | 900s |
| Default `embedding_strategy` | local | local | **server_side** | should be server_side | should be server_side |
| `embedding_dim` | 384 | 384 | 768 | 1024 | 1536 (with text-embedding-3) |
| Proxy | none | cloud-sql-proxy | alloydb-auth-proxy | none | none |
| Bulk embedding API | — | — | `ai.initialize_embeddings` (~400/sec) | Bedrock single-row fallback (~25/sec) | per-row `azure_ai.generate_embeddings` |

## Gotchas

- **`ai.initialize_embeddings()` must run BEFORE any row has an embedding.** Vertex AI has a 4 MB request limit and the call is all-or-nothing. If the pipeline inserts chunks with local embeddings first and you then try to switch to server-side, `ai.initialize_embeddings` fails. Start with `embedding_strategy: server_side` from day one on AlloyDB — don't migrate mid-flight.
- **Transaction coordination requires PostgreSQL on *both* vector and graph roles.** `StorageFacade.transaction()` checks `isinstance(vector_provider, PostgresVectorProvider)` and the same for graph. A mixed LanceDB+Postgres pairing can't use coordinated transactions.
- **Schema migrations create backup tables first** (`migration.py`). Abort leaves the backup; restoration is manual. Don't abort halfway.
- **Entity embedding tables are owned by `PostgresGraphProvider`**, but `PostgresVectorProvider.entity_vector_search` reads them. Initialise graph before vector, or both atomically via the facade.
- **`schema_tracker` is the source of truth for embedding dim.** Don't bypass it by editing the table directly — consistency checks will fail.
- **`connection.py` is shared across all five dialects.** Keep SQL generation, required-extension lists, and other runtime-query behaviour in adapters. Narrowly scoped `backend_type` branching for *connection setup* and *operational defaults* (DSN construction, `pool_size`, `command_timeout`) is fine and already lives here — those settings genuinely differ by backend and aren't adapter-owned. The line to hold: query / dialect behaviour goes in adapters; pool and timeout tuning can stay in `connection.py`.

## When to migrate *to* Postgres

From the top-level scaling guide: once you have graph relationships approaching 100k, need HNSW tuning, go multi-tenant, or need event retention beyond SQLite's comfortable range. See `docs/scaling.md`.
