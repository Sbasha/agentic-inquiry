# Scaling Guide

Practical thresholds for the storage backends agentic-inquiry ships with, and what to do when you hit them. Defaults-by-default guidance lives next to each provider's code:

- `agentic_inquiry/storage/providers/lancedb/AGENTS.md`
- `agentic_inquiry/storage/providers/postgresql/AGENTS.md`
- `agentic_inquiry/storage/providers/sqlite/AGENTS.md`

This doc is the cross-cutting "when should I migrate?" view. It doesn't duplicate the per-backend defaults — it tells you which defaults to stop trusting, and when.

## TL;DR

| Situation | Recommended stack |
|---|---|
| Solo dev on one repo | LanceDB + SQLite (default) |
| Team of <10, self-hosted, one server | LanceDB + SQLite **or** Postgres (pick Postgres if you already run one) |
| Team or product with >100k graph relationships | Postgres + pgvector |
| Need HNSW-tuned vector search, multi-tenant, or event retention >90d | Postgres + pgvector |
| GCP production with server-side embedding | AlloyDB + (SQLite or Postgres events) |
| AWS production | RDS (Bedrock-backed) |
| Azure production | Azure Database for PostgreSQL + Azure OpenAI |

## Role × backend compatibility

| Role | LanceDB | Postgres | CloudSQL | AlloyDB | RDS | Azure | SQLite | Memory |
|---|---|---|---|---|---|---|---|---|
| `vector` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | ✓ (test) |
| `graph` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | ✓ (test) |
| `events` | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| `file_tracker` | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |

Roles can be mixed across backends — `vector_backend`, `graph_backend`, `events_backend`, `file_tracker_backend_v2` in the `storage:` section of `agentic-inquiry.yaml` are independent pointers.

## Thresholds that actually matter

### LanceDB (default vector + graph)

| Signal | Threshold | Why |
|---|---|---|
| **Graph relationships per project** | **~100,000** (bumpable) | `count_relationships_by_type` now honours `storage.max_query_limit` (default 100k) and logs a warning when results hit the ceiling. Raise the config if you have more; migrate to Postgres if the pull-then-bucket aggregation itself is too expensive. |
| Chunks per project | ~10M | Disk I/O becomes the bottleneck. No horizontal scaling. |
| Concurrent vector searches | ~1 | No connection pool; searches serialise through one LanceDB handle. |
| Need to tune index | Day one if your workload is anything but short-text search | IVF_FLAT is hardcoded. HNSW / IVFFlat params aren't threaded through to the LanceDB path — migrate to Postgres if you need tuning. |

If you're about to hit 100k graph relationships and can't immediately migrate, raise `storage.max_query_limit` as a short-term mitigation — the provider honours it and logs a warning when results hit the ceiling, so the truncation stops being silent. If relationship counting itself becomes slow or memory-heavy after raising the ceiling (pull-then-bucket materialises every matching row), migrate the graph role to Postgres.

### SQLite (default events + file_tracker)

| Signal | Threshold | Why |
|---|---|---|
| Sustained event throughput | **~100 events/sec** | `events.queue_max_size=1000`, `batch_size=100`, `flush_interval=1s`. Above this the queue fills and events drop silently. |
| Dropped-event warnings | Any | Means you're already losing audit signal because the queue is overflowing. Treat it as capacity: raise `events.queue_max_size`, tune `batch_size` / `flush_interval`, reduce emission at the source, or migrate events off SQLite. Do **not** reach for `events.sampling_enabled=true` — sampling drops PROGRESS events unconditionally (not just under backpressure), so it isn't backpressure relief. |
| `has_changed()` latency on indexing | >1 s | File tracker has no index on `file_path` alone. Large repos (>50k files) scan a composite index. |
| Concurrent indexing workers | >20 (`processing_semaphore_limit`) | `busy_timeout=10000ms` is the default; it was originally sized for 10 workers and has been retained at 10s at the new 20-worker default because the writer queue drains fast enough in practice. Headroom is tighter — revisit if SQLITE_BUSY surfaces. If you push the semaphore well past 20 (production tier is 20-50), raise `busy_timeout` in lockstep or migrate the events role to Postgres. |
| Event retention requirement | >90 days | SQLite handles it fine on disk, but the combination of no partitioning + `delete_before()` running at full cleanup time starts to show. |

### Postgres family (when you've migrated)

Not really a scaling-out story for most agentic-inquiry workloads — Postgres with pgvector handles millions of rows per tenant at reasonable latencies. Watchpoints:

| Signal | What to check |
|---|---|
| Pool exhaustion | `pool_size` defaults to `5` for AlloyDB (which shares `max_connections=25` on small instances) and `10` elsewhere. Override upward if you run larger AlloyDB tiers; override down if you see concurrent indexing workers timing out on connection acquisition. |
| HNSW build time | Rebuilding HNSW on 10M+ rows takes hours. Use `storage.index_type=ivfflat` + `expected_rows` for bulk loads, then rebuild as HNSW. |
| AlloyDB `ai.initialize_embeddings` | 4 MB Vertex AI request limit. Must run on a table with zero pre-existing embeddings. Start with `embedding_strategy: server_side` on day one — don't migrate mid-flight. |
| RDS bulk embedding | `ai.initialize_embeddings` isn't available on RDS; Bedrock path uses per-row helper (~25/sec). First-time indexing of a large codebase is slow — the 900s `command_timeout` default covers it. |
| `command_timeout` | `60s` for self-hosted Postgres; `900s` for all cloud-hosted variants (`cloudsql`, `alloydb`, `rds`, `azure`) — driven by slow server-side embedding on alloydb/rds/azure, with cloudsql inheriting the long default because it shares the AlloyDB-adjacent tooling path. |

## Migration triggers (by symptom)

**"Search is getting slow on one project"**
Probably chunk count approaching the disk-I/O ceiling on LanceDB. Migrate vector role to Postgres + pgvector with HNSW. Keep graph on LanceDB if relationship count is still under 100k.

**"My relationship counts look wrong"**
You've hit the LanceDB graph aggregation ceiling, which is now driven by `storage.max_query_limit` (default 100k) and logs a warning when the ceiling is reached. Raise the config for a short-term bump; migrate the graph role to Postgres if counts keep creeping past it or aggregation itself is expensive.

**"Events are dropping"**
SQLite event queue is overflowing. Short-term: raise `events.queue_max_size`, tune `batch_size` / `flush_interval`, or reduce event volume at the source. Long-term: migrate `events_backend` to Postgres. Enable `events.sampling_enabled=true` only if PROGRESS events are the dominant contributor to queue pressure — sampling drops them unconditionally whenever it's on (not just under backpressure), so it's a noise dial for PROGRESS-heavy workloads, not a general overflow fix.

**"Indexer is slow to detect changes on a big repo"**
SQLite file tracker without a `file_path` index. Migrate `file_tracker_backend_v2` to Postgres, or shard by project.

**"Need multi-tenant isolation"**
SQLite `project_id` is query-level only. Migrate events + file_tracker to Postgres with row-level security or table-prefix isolation (`storage.table_prefix`).

**"Going to production on GCP"**
Move vector + graph to AlloyDB with `embedding_strategy: server_side`. Events + file_tracker can stay on SQLite if single-node, or join AlloyDB / CloudSQL if you want one store.

## How to migrate

The registry shape supports mixed backends per role — you don't have to cut over all at once.

### Partial migration: keep LanceDB vectors, move graph to Postgres

```yaml
storage:
  backends:
    vectors:
      type: lancedb
      database_path: ./.agentic-inquiry/lancedb
    graph_db:
      type: postgresql
      connection_string: "postgresql://user:pass@host/ai"
      pool_size: 10
    metadata:
      type: sqlite
      database_path: ./.agentic-inquiry/metadata.db
  vector_backend: vectors
  graph_backend: graph_db
  events_backend: metadata
  file_tracker_backend_v2: metadata
```

Re-run `ai index` against your repo. Chunks stay in LanceDB, entities/relationships are written to Postgres. Searches use both (hybrid).

### Full cutover to Postgres

```yaml
storage:
  backends:
    primary:
      type: postgresql
      connection_string: "postgresql://user:pass@host/ai"
      pool_size: 10
      similarity_metric: cosine
      index_type: hnsw
  vector_backend: primary
  graph_backend: primary
  events_backend: primary
  file_tracker_backend_v2: primary
```

Re-indexing is the migration tool — there's no `ai migrate` that copies LanceDB data into Postgres. Existing event history in SQLite doesn't transfer automatically either; export manually if you need it.

### GCP production (AlloyDB server-side embedding)

```yaml
storage:
  backends:
    alloydb:
      type: alloydb
      # AlloyDB takes structured fields, not a connection_string —
      # BackendConfig.validate_alloydb_config requires these six and rejects
      # unknowns via extra="forbid".
      project: my-gcp-project
      region: us-central1
      cluster: my-alloydb-cluster
      instance: my-alloydb-instance
      database: ai
      user: ai_user
      # embedding_strategy / embedding_model / embedding_dim are auto-set to
      # server_side / text-embedding-005 / 768 by validate_alloydb_config —
      # listed here for visibility.
      embedding_strategy: server_side
      embedding_model: text-embedding-005
      embedding_dim: 768
      pool_size: 5          # AlloyDB small: override only if on a larger tier
      command_timeout: 900  # default; raise if ai.initialize_embeddings still times out
  vector_backend: alloydb
  graph_backend: alloydb
  events_backend: alloydb
  file_tracker_backend_v2: alloydb
```

First indexing run:

1. Pipeline inserts chunks with `embedding IS NULL`.
2. After inserts, pipeline calls `generate_embeddings()` on the provider.
3. On a fresh table, `ai.initialize_embeddings()` processes ~400 rows/sec.
4. Subsequent incremental indexing uses per-row `embedding()` (~25/sec).

Do not skip step 1 on day one with `embedding_strategy: local` and then flip to server-side — `ai.initialize_embeddings` only works on a table with zero existing embeddings.

## Defaults worth flagging up front

Every AGENTS.md file has the full evaluation. A recent pass tightened several defaults — here's the current state of the ones most likely to surprise you:

**Fixed:**

1. **LanceDB graph `.limit(100000)` hardcode → honours `storage.max_query_limit`** and logs a warning when results hit the ceiling. Raise the config if your graph is bigger; migrate to Postgres if aggregation itself becomes slow.
2. **AlloyDB `pool_size=10` → backend-aware default.** Now `5` for AlloyDB, `10` for everyone else. Matches AlloyDB small's `max_connections=25` ceiling.
3. **Postgres `command_timeout=60s` → `900s` for all cloud-hosted variants.** Previously only AlloyDB + CloudSQL got the bump; RDS and Azure server-side paths can be just as slow and now get the same treatment.
4. **SQLite `busy_timeout=5s → 10s`**. Aligned with default `indexing.processing_semaphore_limit=20` (raised from 10 after batched-embedding PR #134 let file-level concurrency actually deliver throughput instead of starving on the embedding executor).

**Still needs operator attention:**

1. **Postgres `embedding_dim=384`** when using a server-side embedding model. 768 for AlloyDB `text-embedding-005` (auto-flipped), 1024 for RDS Bedrock (not auto-flipped), 1536 for Azure `text-embedding-3` (not auto-flipped). Until auto-flip covers all variants, set this explicitly on RDS/Azure.
2. **SQLite `events.sampling_enabled=false` is correct, but read the semantics.** The sampler drops PROGRESS events unconditionally when enabled, not just under backpressure. It's a noise dial, not a backpressure bridge. If you see dropped-event warnings, size `queue_max_size` up or migrate events to Postgres before enabling sampling.
3. **Pool / timeout keys in LanceDB configs.** `pool_size`, `max_overflow`, `backend_timeouts.*` are schema-accepted but ignored. No-op noise in `ai setup`'s output; not a runtime issue.

## Testing the migration

`tests/storage/test_facade.py::test_from_config_end_to_end_with_real_registry` exercises the registry path with the `memory` backend — a cheap smoke test that your migration-target config parses and instantiates without hitting the DB. Contract tests in `tests/storage/contracts/` run role-conformance against any backend; point them at your target before going live.
