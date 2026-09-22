# LanceDB Provider

Default backend for the `vector` and `graph` roles. File-based, single-process, no external service. Shipped as the out-of-the-box `ai setup` choice — optimised for individual dev / small team self-hosting.

**Backend type string:** `lancedb` (registry.py).

## File map

| File | Purpose |
|---|---|
| `__init__.py` | Exports `LanceDBConnectionManager`, `LanceDBVectorProvider`, `LanceDBGraphProvider`, `LanceDBMaintenanceOperations`, and the combined (deprecated) `LanceDBProvider` |
| `connection.py` | `LanceDBConnectionManager` — directory creation, DB handle lifecycle, health checks |
| `vector.py` | `LanceDBVectorProvider` — chunk upsert, vector/FTS/hybrid search, `entity_vector_search` |
| `graph.py` | `LanceDBGraphProvider` — entity/relationship upsert, traversal, cascade delete |
| `entity_rows.py` | Shared `dict_to_graph_entity` hydrator — breaks a vector↔graph circular import |
| `maintenance.py` | `LanceDBMaintenanceOperations` — compact, cleanup old versions, integrity checks |

Adjacent: `agentic_inquiry/database/lancedb_manager.py` (lower-level LanceDB handle wrapper) and `agentic_inquiry/database/tables.py` (schema creation / TableManager).

The registry maps both `vector` and `graph` roles to the combined `LanceDBProvider`. New code should prefer the split `LanceDBVectorProvider` + `LanceDBGraphProvider` via `LanceDBConnectionManager` (see the `__init__.py` docstring for the recommended pattern).

## Config surface

Only the keys LanceDB actually consumes — the rest are pooled-backend leftovers that the yaml schema allows but this provider silently ignores.

| Config key | Default | Read by LanceDB? | Notes |
|---|---|---|---|
| `storage.backends.<name>.database_path` | `./.agentic-inquiry/lancedb` (from `ai setup`) | yes | Local path; created on `initialize()` |
| `storage.batch_size` | `1000` | yes, via manager | Upsert chunking |
| `storage.max_query_limit` | `100000` | yes | Row cap on `count_relationships_by_type` pull-then-bucket aggregation |
| `embeddings.default_dimensions` | `384` | yes | Immutable once tables exist |
| `storage.similarity_metric` | `cosine` | yes | Pinned at index build; changing mid-project breaks search |
| `storage.backend_timeouts.*` | various | **no** | Pool / transaction timeouts; LanceDB has neither |
| `storage.backends.<name>.pool_size` / `max_overflow` | — | **no** | pgvector-era leftover |
| `indexing.processing_semaphore_limit` | `20` | indirectly | Caps concurrent writers the provider sees. Raised from 10 after batched-embedding let the executor release faster |

## Defaults evaluation

**What's sensible:**

- `batch_size = 1000` — LanceDB is file-backed; large batches amortise disk writes. Good default.
- `embeddings.default_dimensions = 384` — matches `all-MiniLM-L6-v2` (the default sentence-transformer). Consistent with the LanceDB-canonical 384-dim world.
- `similarity_metric = cosine` — correct default for sentence-transformer embeddings (they're pre-normalised).
- Single-node, single-writer assumption — correct for LanceDB's design.

**Now honoured** (was previously misleading):

- **`storage.max_query_limit` drives graph aggregation.** `count_relationships_by_type` used to hardcode `.limit(100000)`; it now reads `self._connection_manager.config.storage.max_query_limit` and logs a warning when the result count equals the limit (likely truncation). Operators can raise the ceiling without patching provider code, and they find out when they hit it. While doing this fix, a shadowed duplicate `count_relationships_by_type` method was also removed — a pre-existing dead-code clone introduced in Feb 2026.

**Still misleading:**

- **Pool / timeout keys** (`pool_size`, `max_overflow`, `backend_timeouts.transaction_timeout`, `backend_timeouts.migration_lock_timeout`) are accepted in the config schema but LanceDB ignores them. Their presence in `agentic-inquiry.yaml.example` gives the false impression they're tunable here.
- **`storage.lancedb.*`** is a *legacy*-shape alias that `get_lancedb_path()` uses when the registry shape is being auto-migrated. Registry-shape configs should use `backends.<name>.database_path` instead.

**What's genuinely missing:**

- **Index type / tuning isn't exposed.** The tables use whatever `TableManager` creates (currently IVF_FLAT, hardcoded in `database/tables.py`). `storage.index_type` / `index_params` / `expected_rows` fields exist on `BackendConfig` but aren't threaded through to the LanceDB path. If you need HNSW or tuned IVFFlat, migrate to Postgres + pgvector (see `docs/scaling.md`).
- No connection pool, even for read concurrency. Concurrent searches serialise through the single LanceDB handle.

## Scaling signals in this provider

- `graph.py:_max_query_limit` — graph aggregation ceiling driven by `storage.max_query_limit` (default 100k). A warning log fires when results hit the ceiling, so truncation stops being silent.
- No row-count warnings at write time. `upsert_chunks` will happily keep going past any target size; performance degrades gracefully until you hit the aggregation ceiling or disk I/O.
- Perf benchmarks (`tests/performance/test_perf_improvements.py`) top out at ~1000 entities / 500 relationships. Above this, you're extrapolating.

## Gotchas

- **No server-side embedding.** `vector.py` rejects `str` queries in `entity_vector_search` (LanceDB has no embedding function). Callers must pass `List[float]`. AlloyDB / RDS can pass strings — LanceDB can't.
- **Thread safety is best-effort.** Operations wrap in `asyncio.to_thread`. Reads are fine concurrently; concurrent writes to the same table can contend on Lance's internal lock. The indexing pipeline's `processing_semaphore_limit=20` (default) is the de-facto safety valve — was 10 until the batched-embedding PR let the executor release faster.
- **`dict_to_graph_entity` returns `None` on failure** and callers log-and-skip. Schema-mismatch rows vanish silently.
- **Cascade delete is N+1.** `delete_entities_by_ids` → `delete_relationships_by_entity` per entity. Fine for interactive edits, painful for bulk cleanup on highly-connected graphs.
- **BFS traversal in `get_neighbors`** fires one query per depth level. Deep or high-fan-out graphs generate many round trips.
- **Changing `similarity_metric` after the index is built misaligns search.** No immutability guard here (similar to embedding dim, which *does* have a guard). Pick cosine and don't change it.
- **Combined `LanceDBProvider` is legacy.** Don't use it for new code — lifecycle is cleaner with the split providers sharing one `LanceDBConnectionManager`.

## When to migrate off LanceDB

See `docs/scaling.md` for thresholds. Short version: when you hit >100k graph relationships, need HNSW tuning, or go multi-tenant / distributed.
