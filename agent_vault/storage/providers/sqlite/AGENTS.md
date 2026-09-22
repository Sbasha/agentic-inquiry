# SQLite Provider

Default backend for the `events` and `file_tracker` roles. **Does not serve vector or graph.** Local file-based, single-writer + WAL reads. Paired with LanceDB by default (`agv setup`) for a zero-external-dependencies dev setup.

**Backend type string:** `sqlite` (registry.py).

## File map

| File | Purpose |
|---|---|
| `__init__.py` | Exports `SQLiteEventProvider`, `SQLiteFileTrackerProvider` |
| `events.py` | `SQLiteEventProvider` wraps `SQLiteEventStorage`; adds `run_maintenance()` → `VACUUM` |
| `file_tracker.py` | `SQLiteFileTrackerProvider` wraps `FileTracker`; adds async `close()` + `get_hash_sync()` |

The actual schema and writer logic live outside this directory:

- `agent_vault/events/storage/sqlite.py` — `SQLiteEventStorage`: schema, WAL setup, batch writes, query/delete, vacuum. This is where PRAGMAs are set (lines 100-102).
- `agent_vault/watching/file_tracker.py` — `FileTracker`: SHA256-based change detection with composite key `(project_id, file_path)`.

The provider classes are thin protocol-conformance wrappers; if you're debugging write throughput or lock contention, go to the parent classes.

## Config surface

| Config key | Default | Notes |
|---|---|---|
| `storage.event_store_backend` | `"sqlite"` | Legacy field; registry shape uses `backends.<name>` instead |
| `storage.file_tracker_backend` | `"sqlite"` | Legacy field |
| `backends.<name>.database_path` (also `path`, `db_path`) | — | Three aliases, all resolved in `SQLiteEventProvider.__init__` |
| `storage.event_store.path` | `"events.db"` | Default filename under `storage.root` |
| `storage.file_tracker.path` | `"file_tracker.db"` | Default filename under `storage.root` |
| `events.queue_max_size` | `1000` | In-memory buffer before backpressure |
| `events.batch_size` | `100` | Events per disk flush |
| `events.flush_interval_seconds` | `1.0` | Soft flush deadline |
| `events.retention_days` | `30` | `delete_before()` cutoff |
| `events.cleanup_interval_hours` | `24` | Retention job cadence |
| `events.sampling_enabled` | `false` | When true, routine PROGRESS events are sampled |
| `events.sampling_ratio` | `10` | Keep 1-in-N when sampling |
| `events.retry_max_attempts` | `5` | `database is locked` retry |
| `events.retry_base_delay_seconds` | `0.1` | Exponential backoff base |

PRAGMAs (the same set is applied in three places — keep them in sync):

- `agent_vault/events/storage/sqlite.py` — `SQLiteEventStorage.initialize()`
- `agent_vault/events/store.py` — legacy `EventStore._ensure_initialized()`
- `agent_vault/onboard/providers/sqlite.py` — `SQLiteOnboardMetadataProvider.initialize()`

| PRAGMA | Value |
|---|---|
| `journal_mode` | `WAL` |
| `synchronous` | `NORMAL` |
| `busy_timeout` | `10000` (10 s) |

The onboard-metadata path used to set only `journal_mode=WAL` and inherit SQLite's default `busy_timeout=0`, which meant any lock contention failed immediately. Bringing it in line was part of the defaults-tightening pass; if you're adding a new SQLite writer, copy the three-PRAGMA block verbatim.

## Defaults evaluation

**Sensible:**

- **`journal_mode=WAL`** — right call. Lets reads proceed while the single writer is active; trades a second file (`.wal`/`.shm`) for non-trivial concurrency on reads.
- **`synchronous=NORMAL`** — reasonable durability/speed tradeoff for dev. Not `FULL` (which fsyncs every write) and not `OFF` (which loses acknowledged writes on crash). Good default for the intended use case.
- **`busy_timeout = 10000ms`** — originally sized for `processing_semaphore_limit=10`; kept at 10s after the semaphore default rose to 20 because in practice the writer queue drains fast enough that SQLITE_BUSY hasn't surfaced. Headroom is tighter now. Was previously 5 s at a 10-worker default, which *did* surface `SQLITE_BUSY` under bursty indexing. Revisit if SQLITE_BUSY reports start coming in, and raise in lockstep if operators push the semaphore well past 20.
- **Single persistent writer connection** — correct pattern. All writes serialise through one connection, avoiding `SQLITE_BUSY` under concurrent producers. Reads open short-lived connections.
- **`events.batch_size = 100`, `flush_interval = 1.0s`** — ~100 events/sec sustained is plenty for dev workflows (single engineer indexing one repo).
- **`events.retention_days = 30`** — right for dev, where nobody's looking at events older than a week.

**Needs attention at scale:**

- **`events.queue_max_size = 1000`** handles ~100 events/sec sustained comfortably. A burst of 10 concurrent workers emitting 100 events each can fill it; events beyond the ceiling drop with a warning log. Raise the ceiling or migrate `events` to Postgres before chasing sampling — see gotcha below.
- **`events.sampling_enabled = false`** is the correct default but deserves understanding. The sampler runs *unconditionally* on PROGRESS events when enabled — it drops roughly `(ratio-1)/ratio` of them regardless of queue depth, not just under backpressure. That makes it a noise-reduction dial, **not** a backpressure bridge. If you're seeing dropped-event warnings, size `queue_max_size` up or migrate events to Postgres. Turn sampling on only when PROGRESS noise dominates your event volume and sampling the bulk of it is intentional.
- **File tracker lacks an index on `file_path` alone.** The PRIMARY KEY is `(project_id, file_path)`, which covers lookups from within a project. But `has_changed()` queries on large repos (50k+ files) walk the composite index. Fine for typical projects, noticeably slower as repo size grows.

**Genuinely wrong:**

- `retention_days = 30` in a shared self-hosted deployment where someone *is* looking at events: 30 days is too short for post-incident review. Raise to 90+ and watch disk use.

## Concurrency model

```
writers ──▶ asyncio.Queue (max=1000) ──▶ single persistent writer connection
                                              │  (WAL)
readers (per-query new connections) ◀─────────┘
```

- Events are batched (100 events or 1s, whichever first) and written via `executemany()`.
- On `SQLITE_BUSY`, retries with exponential backoff (max 5 attempts).
- `wal_checkpoint(TRUNCATE)` runs on `close()` and inside `delete_before()` — briefly blocks other writers.

Throughput ceiling is essentially SQLite disk write speed (~1-10 MB/s) divided by row size. In practice: hundreds of events/sec sustained, thousands in bursts before the queue backpressure kicks in.

## Scaling signals

- `queue_max_size=1000` — at ~100 events/sec steady throughput, a 10-second stall fills it.
- `retry_max_attempts=5` on lock contention — after this the event is dropped.
- File tracker: no index on `file_path` alone; `has_changed()` cost grows with repo size.
- Connection-per-query read pattern — at >100 queries/sec, the `aiosqlite.connect()` overhead starts dominating.

## Migration path

Both `events` and `file_tracker` can move to Postgres. The unified `postgresql` provider serves both roles (see `../postgresql/AGENTS.md`). In `agent-vault.yaml.example`, point the role to a Postgres backend:

```yaml
storage:
  backends:
    primary:
      type: postgresql
      connection_string: "postgresql://..."
  events_backend: primary
  file_tracker_backend_v2: primary
```

No migration tool ships for moving existing SQLite data — Postgres providers create schemas on first `initialize()`. If event history matters, export manually. File tracker state can usually just be rebuilt by re-indexing.

## Gotchas

- **`asyncio.run()` in sync wrappers.** `FileTracker.update_hash_sync`, `has_changed_sync`, `remove_file_sync`, `get_hash_sync` create a new event loop. Calling them from an async context raises `RuntimeError: asyncio.run() cannot be called from a running event loop`. Use the async variants when you're already in async code.
- **Silent event drops** when the queue fills. `put_nowait` raises `asyncio.QueueFull` internally, which `EventSystem.emit` catches and turns into an `events_dropped_count` increment plus a `logger.warning`; the caller of `emit()` never sees an exception or a delivery ack. With `sampling_enabled=false` (default), a busy indexer can lose diagnostic signal without any alerting surface.
- **No project-isolation enforcement at the database level.** `project_id` is just a query column. A bug in filter construction can leak data across projects. Covered by `tests/storage/test_project_isolation.py`; don't weaken those tests.
- **WAL checkpointing blocks writes.** `close()` flushes via `wal_checkpoint(TRUNCATE)`. If many writes are pending, close can take seconds. `close_timeout` defaults to 5.0s in the event system.
- **Reads open a fresh connection every time.** At sustained high query rates this becomes the bottleneck; no pooling.
- **Monotonic sampling counter.** When sampling is enabled, the counter increments forever — its modulo is what drives keep/drop decisions. Correct long-term, but the emitted / sampled metric counters grow unbounded until restart.

## When to migrate off SQLite

See `docs/scaling.md`. Rough triggers: sustained >100 events/sec, dropped-event alerts firing in normal operation, file tracker queries taking >1s on `has_changed`, event retention requirement >90 days.
