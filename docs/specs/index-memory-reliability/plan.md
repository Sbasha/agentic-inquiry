# Plan: Index and memory write honesty

> Historical reference. This page describes PostgreSQL-family providers, cloud connectors or remote embedders that are not part of this local-only distribution. It is retained as design input for the external provider contract in [storage-backends.md](../../storage-backends.md).

- **Spec:** [`spec.md`](spec.md)
- **Status:** Approved

> **Plan contract:** this is the implementation strategy. Unlike the spec, this
> document is allowed to change as you learn. When it changes substantially
> (a different approach, not just a re-ordering), note why in the changelog
> at the bottom.

## Approach

Four seams on the same post-index path, each testable alone: collapse
duplicate merge keys in `_upsert_rows`, stop swallowing graph-write
failures so `ai index` exits 1, make `ai memory save` verify the row
on the canonical tables, then print the CPU hatch on Darwin before the
embedder loads. No new libraries. No lock manager. Storage tests use
on-disk LanceDB.

Riskiest part: keep-last collapse must not drop unique edges, and
memory read-back must fail closed on the in-memory fallback without
claiming success.

Second pass (2026-09-21), after the first four seams shipped and a
1,442-file index still exited 1 with 208 failed files: three more seams
on the LanceDB write path. First replace the removed Tantivy
multi-column FTS index with a native single-column index on `fts_text`
(T6). Then serialize same-table open/create, index creation, writes,
and maintenance with one in-process lock per table owned by
`TableManager`, and drop the per-write `optimize()` that generated the
conflicting `Rewrite` / `CreateIndex` transactions (T5). Then qualify
on the real corpus with receipts (T7). Riskiest part: removing
`optimize()` must not break search visibility (probed: it does not),
and the lock must not starve the pipeline (writes are milliseconds once
`optimize()` is gone).

## Constraints

- No RFC: bug fixes inside existing modules, not a charter or convention
  change.
- Sibling spec [`../first-run-reliability/spec.md`](../first-run-reliability/spec.md)
  stays frozen: do not amend it; do not reopen onboard warning, chunk
  exit codes, retry filter, or env-file load rules.
- `Never do` in this spec: no `python-dotenv`, no default CPU, no lock
  manager, no LanceDB FirstSeen, no Salesforce indexer work, no Gemini
  or Codex conversion, no hand-edited `CHANGELOG.md`.

## Construction tests

Most construction tests live under **Tasks** below (per-task `Tests:`
subsections). This top-level section is only for cross-cutting tests that
span tasks.

**Integration tests:** none beyond per-task tests. Collapse, index
status, memory honesty, and the hatch hint do not share a single new
integration surface.

**Manual verification:** on a temp LanceDB env, `ai memory save -i 0.85
--project demo` then `ai memory list --project demo` shows the row;
`ai index` summary still prints when a graph write forces exit 1.

## Design (LLD)

Shape is `mixed`. UI-only sub-sections (state and control flow) are
omitted. Stack is the existing Python CLI + LanceDB path
(`agentic_inquiry/database/lancedb_manager.py`, `agentic_inquiry/cli/`,
`agentic_inquiry/memory/`). No `docs/architecture/reference.md` is present.

### Design decisions

- Collapse duplicate merge keys in `_upsert_rows` (keep last, log
  count), not LanceDB FirstSeen. Traces to AC 1. Alternative (database
  silent drop) has no documented Python API and no log.
- Graph write failure sets index status to `completed_with_errors` or
  `failed` and exits 1; chunk rows stay. Traces to AC 2. Alternative
  (rollback chunks) is a new transaction subsystem.
- Memory save verifies with `get_by_id` after `store()`. Traces to
  AC 4-5. Alternative (fake multi-table transaction) does not exist on
  LanceDB.
- Table names come from `config.memory.*.table_name`. Traces to AC 3.
- Darwin hatch hint prints to stderr before embedder construction.
  Traces to AC 7-8. Alternative (docs-only) misses a global `ai` that
  has not been reinstalled.
- One `asyncio.Lock` per table name, owned by `TableManager`
  (`table_lock(name)`), taken around open/create plus
  `_ensure_indexes_sync` in `get_table`, `get_or_create_table`, and
  `create_table_from_schema`, around `_ensure_indexes_sync` in
  `LanceDBSchemaManager.create_tables_and_indexes`, and by
  `LanceDBManager` around the write in `_add_rows`, `_upsert_rows`,
  `_delete_rows`, and per table in `compact_tables`,
  `cleanup_old_versions`, and `rebuild_fts_indexes`. Order: per-table
  lock outer, `TableManager._lock` inner; a method never holds the
  per-table lock while calling a method that takes it (table
  acquisition and the write are two separate critical sections).
  Traces to AC 9, AC 10, AC 14. Alternatives: a file lock (Ask first;
  no cross-process conflict was observed) or a smaller semaphore (still
  races).
- No `optimize()` on the write path; `_flush_table` and the
  `ensure_commit` branch go away. The `ensure_commit` parameter stays on
  the protocol and adapters (public interface; the in-memory test
  manager and the PostgreSQL provider share the signature) with
  docstrings that say LanceDB commits on return. Traces to AC 11.
  Alternative (keep it behind `ensure_commit`) keeps the conflict
  source reachable; alternative (delete the parameter) is a protocol
  change across every backend for no behavior gain.
- `TABLE_CONFIGS["document_chunks"]` moves from `fts_text_columns`
  (three columns, Tantivy) to `fts_columns: ("fts_text",)`; the
  multi-column branches in `tables.py` and `schema_manager.py` are
  deleted. `rebuild_fts_indexes` stays: native FTS answers queries over
  rows written after the index was built by scanning them, so the
  rebuild is a performance step after bulk writes, not a correctness
  step; its docstring says so. Traces to AC 12. Alternative (pin
  lancedb below the Tantivy removal) leaves the installer on an
  unsupported path; alternative (second index on `content`) is in the
  spec's Declined patterns.

### Data & schema

No new tables and no column changes. Persistent memory uses existing
schema names `memory_episodic_medium` and `memory_semantic_high`
(config defaults). `LanceDBMemoryAdapter.initialize()` creates the
adapter table via the manager if it is missing. Empty leftover
`memory_episodic` / `memory_semantic` directories, if any, are unused.
Traces to AC 3. · contracts: none.

### Interfaces & contracts

No OpenAPI / MCP contract file. Public CLI behavior:

- `ai index` exit 1 and a graph-write failure line when
  `add_graph_relationships` fails. Traces to AC 2.
- `ai memory save` success line and exit 0 only after read-back.
  Traces to AC 4-5.
- `--project` on save/list/recall is stored and used as a filter.
  Traces to AC 6.

`exit_code_for_index_result` in `agentic_inquiry/cli/index.py` already
returns 1 for any status other than `completed` with chunks; T2 feeds
it a non-`completed` status. Traces to AC 2.

### Component / module decomposition

- Dedupe helper next to `_upsert_rows` in
  `agentic_inquiry/database/lancedb_manager.py`.
- Graph-write failure propagation in
  `relationship_batch_processor.commit_batch`,
  `graph_builder._commit_batch`, and `IndexingPipeline` flush paths.
- Memory honesty in `agentic_inquiry/cli/memory.py` (verify, project
  context, reject in-memory fallback) plus adapter initialize and
  `MemorySystem` table names from config.
- Hatch hint helper on `agentic_inquiry/cli/env_resolver.py` (env path is
  already resolved there); called from `index.py` and `memory.py`.
  Not a new package.
- Per-table lock and write path in
  `agentic_inquiry/database/lancedb_manager.py`; FTS config in
  `agentic_inquiry/database/lancedb_schemas.py`; index creation in
  `agentic_inquiry/database/tables.py` and
  `agentic_inquiry/database/schema_manager.py`.
- Qualification scripts (receipt runner, read-only index inspector)
  live under `~/.agentic-inquiry/qualification/index-durability-20260921/work/`,
  outside the repository, because they name the private corpus.

Traces to AC 1-17. · contracts: none.

### Failure, edge cases & resilience

- Duplicate keys: collapse, then `merge_insert`. If the write still
  fails (non-retryable), do not retry; fail the index.
- Unique-key batch that still raises Ambiguous merge: fail the index;
  do not add a lock (Ask first).
- Memory store exception, missing table after write, or in-memory
  adapter: exit 1, no success line.
- Working memory (`importance < 0.7`): exit 1, session-only message.
- Embedding device: CPU unless CUDA is available; MPS only when
  `INQUIRY_EMBEDDING_DEVICE=mps` is set. Process kill 137/139 remains
  uncatchable, which is why MPS is never autodetected.
- Cross-process commit conflict (another `ai` process writing the same
  table): still retried five times with backoff, then fails the file.
- Reader in another process holding a version older than five minutes
  when `run_maintenance` prunes: unchanged, out of scope.
- Legacy duplicate-key rows left by the unserialized writer: not
  repaired (Ask first); `merge_insert` updates every copy (AC 13
  construction test; probe on the real table). The comparator candidate
  is built fresh so it carries none.

Traces to AC 2, 4, 5, 7, 9, 13, 14, 15.

### Quality attributes (NFRs)

- Honesty: exit 0 only when the claimed write is readable (index graph
  or memory row).
- Operability: a default install cannot reach the Metal abort; opting
  into MPS is an explicit env-file edit.
- No new dependency; retry predicates unchanged from first-run
  reliability.

Traces to AC 2, 4, 7.

## Tasks

### T1: Duplicate merge keys collapse to one row (last wins)

**Depends on:** none

**Touches:** agentic_inquiry/database/lancedb_manager.py, tests/database/test_lancedb_merge_dedupe.py

**Mode:** TDD

**Tests:**
- On-disk LanceDB: upsert two `graph_relationships` rows with the same
  `(id, project_id)` and different `metadata`; after `_upsert_rows` the
  table has one row whose `metadata` matches the second input (AC 1).
  stub: true (`tests/database/test_lancedb_merge_dedupe.py`)
- Same batch with one unique extra key: two rows remain, unique key
  intact (AC 1).
  stub: true
- Existing `tests/database/test_lancedb_retry.py` stays green (retry
  predicates unchanged).
  stub: true (`test_is_retryable_lancedb_error` Ambiguous-merge case)

**Approach:**
- After normalize and validate in `_upsert_rows`, collapse `rows` by
  the `key_column` (str or list of str). Keep last occurrence. If any
  rows were dropped, `logger.info` the table name and collapse count.
- Do not change `_is_retryable_lancedb_error` or `RetryPolicy`.

**Done when:** `tests/database/test_lancedb_merge_dedupe.py` is green
and retry tests still pass.

### T2: Graph write failure makes `ai index` exit 1

**Depends on:** T1

**Touches:** agentic_inquiry/indexing/relationship_batch_processor.py, agentic_inquiry/indexing/graph_builder.py, agentic_inquiry/indexing/pipeline.py, tests/indexing/test_flush_relationships.py, tests/cli/test_index_exit_code.py, tests/database/test_lancedb_retry.py

**Mode:** TDD

**Tests:**
- When `add_graph_relationships` raises, `commit_batch` / flush does
  not return success; the error is visible to the pipeline (AC 2).
  stub: true (`tests/indexing/test_graph_write_failure.py`)
- Pipeline result `status` is `completed_with_errors` or `failed` when
  the graph write fails, even if chunks were written (AC 2).
  stub: true
- A pipeline/CLI result with graph-write failure and
  `chunks_created > 0` has status other than `completed`,
  `exit_code_for_index_result` returns 1, and the printed summary
  contains the graph write error text (AC 2).
  stub: true
- `_is_retryable_lancedb_error` is false for `Ambiguous merge inserts
  are prohibited` (AC 2).
  stub: true

**Approach:**
- Stop treating `commit_batch` failure as log-only in
  `RelationshipBatchProcessor.commit_batch` and
  `GraphBuilder._commit_batch`. Propagate or return a failure the
  pipeline cannot ignore.
- In `IndexingPipeline`, do not swallow `flush_pending_relationships`
  errors (including the per-document flush). Set status to
  `completed_with_errors` or `failed` and put the error text on the
  result the CLI prints.
- Leave document chunks in place. Do not add a lock.

**Done when:** flush / pipeline tests green;
`tests/cli/test_index_exit_code.py` still maps non-completed status to
1.

### T3: `ai memory save` exits 0 only when the row is readable

**Depends on:** none

**Touches:** agentic_inquiry/cli/memory.py, agentic_inquiry/memory/system.py, agentic_inquiry/memory/adapters/lancedb_adapter.py, tests/cli/test_memory_exit_code.py, tests/memory/test_lancedb_integration.py

**Mode:** TDD

**Tests:**
- Importance 0.85 and 0.9 against temp LanceDB: `save_command` exits 0;
  a following `list_command` / `recall_command` for the same project
  returns that id; the table on disk is `memory_episodic_medium` or
  `memory_semantic_high` (AC 3, AC 4). `get_by_id` may be used as an
  extra probe, not as a substitute for list/recall.
  stub: true (`tests/cli/test_memory_exit_code.py`)
- Failed `store`, missing row on read-back, or in-memory adapter
  fallback: exit 1, stdout does not contain `Memory saved:` (AC 4).
  stub: true
- Importance 0.5: exit 1, message mentions session-only / not
  persisted, no `Memory saved:` (AC 5).
  stub: true
- `--project demo` is stored on the row; list/recall with that project
  return it; a different project does not (AC 6).
  stub: true
- After `initialize()` on a fresh LanceDB dir, the configured table
  exists (row count may be 0) (AC 3 construction).
  stub: true

**Approach:**
- Pass `config.memory.episodic_memory.table_name` and
  `semantic_memory.table_name` into adapters from `_create_memory_system`
  and from `MemorySystem` when it builds adapters internally.
- `initialize()`: after `connect()`, create the table from
  `get_schema()` if it does not exist.
- Pass `project_id` into `create_agent_context` in save, list, and
  recall. Filter list/recall by that project id.
- After `store()`, if tier is working, exit 1. Otherwise `get_by_id`;
  missing row exits 1. Print `Memory saved:` only after the read-back.
- In-memory fallback: print the warning and return 1 (do not save).

**Done when:** `tests/cli/test_memory_exit_code.py` is green.

### T4: Darwin hatch hint prints before embedder load when device is unset

**Depends on:** none

**Touches:** agentic_inquiry/cli/env_resolver.py, agentic_inquiry/cli/index.py, agentic_inquiry/cli/memory.py, tests/cli/test_env_resolver.py, README.md

**Mode:** TDD (device selection) and goal-based (README / commented pin)

**Tests:**
- With fake torch reporting MPS built and available and no pin,
  `_select_device` returns `cpu`; with `preferred="mps"` it returns
  `mps` (`tests/embeddings/test_sentence_transformer_device.py`, AC 7).
- Goal-based: `LocalSetup` env text contains
  `# INQUIRY_EMBEDDING_DEVICE=mps` (existing
  `tests/cli/setup/test_local_setup.py`).
  no stub (mode)
- Goal-based: README contains `uv tool install . --reinstall` and
  `INQUIRY_EMBEDDING_DEVICE=mps` (AC 8).
  no stub (mode)

**Approach:**
- `_select_device` autodetects CUDA only. MPS is returned solely for an
  explicit `mps` pin. No Darwin hint is needed because the default path
  cannot abort.
- README: after the `uv tool install .` getting-started note, add
  reinstall (`uv tool install . --reinstall`) so a previously
  installed global `ai` picks up the env-file loader, and state that
  Metal is opt-in.
- Do not edit `CHANGELOG.md`. Living architecture docs may mention the
  hatch in the same PR only if the implementing change touches that
  page; it is not a task requirement.

**Done when:** hint tests green; `rg 'uv tool install . --reinstall'
README.md` matches; LocalSetup hatch remains commented.

### T5: Same-table writes, index creation, and maintenance are serialized; no per-write optimize

**Depends on:** T6

**Touches:** agentic_inquiry/database/lancedb_manager.py, agentic_inquiry/database/tables.py, agentic_inquiry/database/schema_manager.py, agentic_inquiry/database/adapters/lancedb_adapter.py, agentic_inquiry/storage/protocols/indexing.py, agentic_inquiry/storage/protocols/vector.py, agentic_inquiry/indexing/schema_processor.py, agentic_inquiry/parsers/implementations/unified_code.py, tests/database/test_lancedb_write_serialization.py, tests/database/test_lancedb_fts_index.py, tests/database/test_maintenance.py

**Mode:** TDD

**Tests:**
- On-disk LanceDB: 16 concurrent `add_graph_relationships` calls, eight
  sharing the same 300 new keys; all return; `caplog` holds no
  `retrying in` warning; one row per distinct key (AC 9). Same shape
  for `add_document_chunks` and `add_graph_entities`.
  stub: true (`tests/database/test_lancedb_write_serialization.py`)
- One manager: first write creates `document_chunks`, then
  `invalidate_table_cache`, then 16 concurrent writes; all return; no
  `Failed to create` warning in `caplog`; `list_indices()` shows one
  vector and one FTS index (AC 10).
  stub: true
- Two managers on one fresh directory race to create
  `document_chunks`; both writes return and the table holds both
  batches (AC 10 construction: the loser of the create race still
  writes).
  stub: true
- `create_table_from_schema` on a missing table returns a table and
  does not hang (memory adapter `initialize()` path; the method resolves
  the table through `get_table` before taking the lock).
  stub: true
- After `add_document_chunks` returns: fresh `lancedb.connect` counts the
  row; `advanced_filter` and `fts_search` on the same manager return it
  (AC 11). Construction assertion: the table object's `optimize`,
  `compact_files`, and `cleanup_old_versions` are not called during the
  write (spy).
  stub: true
- Table pre-seeded through `lancedb` with two rows for one key;
  `_upsert_rows` of one row for that key returns; both copies carry the
  new payload (AC 13).
  stub: true
- `run_maintenance(cleanup_older_than=timedelta(0))` concurrent with 16
  writes to the same table: no errors on either side; no `retrying in`
  warning; every row present afterwards (AC 14).
  stub: true
- Existing `tests/database/test_lancedb_retry.py`,
  `test_lancedb_merge_dedupe.py`, `test_maintenance.py`,
  `test_schema_manager.py` stay green.
  no stub (existing)

**Approach:**
- `TableManager.table_lock(name) -> asyncio.Lock` backed by a
  `defaultdict`; `TableManager._lock` shrinks to cache-dictionary
  access. `get_table` and `get_or_create_table` check the cache, then
  hold the table lock around re-check, open/create, cache insert, and
  `_ensure_indexes_sync`. `create_table_from_schema` calls `get_table`
  (which takes and releases the lock) and only then takes the lock
  itself; `asyncio.Lock` is not reentrant, so no method holds the table
  lock while calling another method that takes it.
- `get_or_create_table` creates without `exist_ok`; if another
  connection created the table first, it opens it and returns
  `created=False` so the caller upserts its rows instead of dropping
  them.
- Index-creation failures inside `_ensure_indexes_sync` keep their
  warning-and-continue behavior; under the lock a single manager issues
  one `CreateIndex` per index, so no conflict arises in-process.
- `LanceDBSchemaManager` receives `table_lock` and holds it around its
  `_ensure_indexes_sync`.
- `_add_rows`, `_upsert_rows`: resolve the table first (which takes and
  releases the lock), then hold the lock around `add` /
  `merge_insert`. `_delete_rows`, `compact_tables`,
  `cleanup_old_versions`: resolve the table with `_get_table_async`
  first, then open a separate critical section under the table lock
  around `delete` / `compact_files` / `cleanup_old_versions`.
  `rebuild_fts_indexes` locks inside `TableManager`.
- `remove_legacy_fts_index(table)` in `tables.py` deletes a Tantivy-era
  `_indices/fts` directory before any `create_fts_index` call (both
  `_ensure_indexes_sync` sites and the rebuild path).
- `compact_tables` and `cleanup_old_versions` call `Table.optimize`:
  the compaction step passes a far-future `cleanup_older_than` so it
  prunes nothing; the cleanup step passes the caller's window.
  `compact_files` / `cleanup_old_versions` need pylance on 0.38.0 and
  fail there, which the 0.38.0 gate exposed.
- Delete `_flush_table` and the `if ensure_commit:` branches. Update the
  `ensure_commit` docstrings at the listed call sites and the
  `rebuild_fts_indexes` docstring in `lancedb_manager.py` to say LanceDB
  commits on return and native FTS scans rows written after the index.
- Leave `_retry_lancedb_write` and its predicates unchanged.

**Done when:** new test file green; retry, dedupe, maintenance, and
schema-manager tests green.

### T6: Native single-column FTS index on `fts_text`

**Depends on:** none

**Touches:** agentic_inquiry/database/lancedb_schemas.py, agentic_inquiry/database/tables.py, agentic_inquiry/database/schema_manager.py, docs/development/adapter-implementation-guide.md, tests/database/test_schema_manager.py, tests/database/test_lancedb_fts_index.py

**Mode:** TDD (index shape) and goal-based (both LanceDB versions)

**Tests:**
- On-disk: a new `document_chunks` table lists exactly one FTS index
  with columns `("fts_text",)` (AC 12).
  stub: true (`tests/database/test_lancedb_fts_index.py`)
- On-disk: create `document_chunks` with `lancedb` directly with rows
  and a vector index only; opening through the manager adds the
  `fts_text` FTS index (AC 12).
  stub: true
- On-disk: seed `<table>.lance/_indices/fts` under a raw table; opening
  through the manager removes it, creates the native index, and
  `fts_search` finds a row written afterwards (AC 12).
  stub: true
- `fts_search` and `hybrid_search` return the row for a fragment that
  appears in `fts_text` only as a camelCase split (`parse` for
  `parseDocument`) (AC 12).
  stub: true
- `tests/database/test_schema_manager.py`: the multi-column case is
  replaced by an assertion that `create_fts_index` is called once per
  configured column with a string, never a list, never
  `use_tantivy=True` (AC 12).
  stub: true
- Goal-based: `tests/database/` passes under lancedb 0.38.0 in the
  qualification venv (AC 12).
  no stub (mode)

**Approach:**
- `TABLE_CONFIGS["document_chunks"]["fts_columns"] = ("fts_text",)`;
  remove `fts_text_columns`.
- Delete the multi-column branches in `tables.py`
  (`_ensure_indexes_sync`, `_rebuild_fts_indexes_sync`) and
  `schema_manager.py`. Reword the `rebuild_fts_indexes` docstrings:
  native FTS scans rows written after the index; the rebuild folds them
  into the index for speed.
- `remove_legacy_fts_index(db_uri, table_name)` runs before every
  `create_fts_index` call: lancedb 0.38.0 refuses to build a native
  index while the Tantivy directory exists and 0.25.2 routes queries to
  it, so the upgrade path needs the delete. The path is built from the
  connection's local URI and the configured table name, canonicalized,
  prefix-checked against the database root, and refused when the index
  directory, its parent, or the table directory is a symlink; the
  intended delete is logged before it runs; `FileNotFoundError` from a
  concurrent remover counts as removed; other `OSError`s are logged
  under their own message. Another process with the table open may see
  one FTS query fail during the removal; it would have failed on the
  legacy index anyway. Accepted: a process that can replace a path
  component between the symlink check and the delete already has write
  access to the dataset directory.
- `docs/development/adapter-implementation-guide.md`: the FTS bullet
  names `fts_text` and PostgreSQL's `file_path` weighting.

**Done when:** new test file and schema-manager tests green on 0.25.2;
`tests/database/` green on 0.38.0.

### T7: Qualify on the real corpus with receipts

**Depends on:** T5, T6

**Touches:** docs/specs/index-memory-reliability/spec.md, docs/specs/index-memory-reliability/notes/qualification-2026-09-21.md, docs/backlog.md

**Mode:** Visual / manual QA

**Tests:**
- Receipt `01-*`: branch HEAD before T5/T6 against a clone of the real
  partial index reproduces `Retryable commit conflict` retries on the
  same corpus and records wall-clock (AC 15 baseline).
  no stub (mode)
- Receipt `10-*`: fixed code, same clone, `ai index` exit 0, zero
  conflict / ambiguous / not-found lines, any failed file attributed to
  a non-write cause (AC 15).
  no stub (mode)
- Receipt `11-*`, `12-*`: fresh-process `ai status` and `ai search`
  against that index; counts match the read-only inspector (AC 15).
  no stub (mode)
- Receipt `20-*`: second `ai index` run; chunk and entity distinct-key
  counts unchanged, duplicate-key rows not grown, relationship growth
  recorded (AC 16).
  no stub (mode)
- Receipt `30-*`: uninterrupted fresh index of the corpus into an empty
  environment; distinct-key counts and files per minute recorded, at
  least 32 files per minute (AC 15 throughput bound; AC 16 reference;
  the comparator candidate).
  no stub (mode)
- Receipt `21-*`, `22-*`: fresh environment, run killed with SIGTERM
  after the first files land, full re-run, chunk and entity distinct-key
  counts equal to `30-*` (AC 16).
  no stub (mode)
- Receipt `40-*`: one search-to-source journey: query, returned
  `file_path`, line range, SHA-256 of the corpus file, and a check that
  the returned content is a substring of that file (AC 17).
  no stub (mode)
- `notes/qualification-2026-09-21.md`: redacted summary of every
  receipt (counts, exit codes, wall-clock, error-class tallies,
  SHA-256s; no corpus paths or content) (AC 15).
  no stub (mode)

**Approach:**
- All runs use the isolated venv with lancedb 0.38.0 and the branch
  checkout installed, `INQUIRY_EMBEDDING_DEVICE=cpu`, the comparator env
  config, and `--skip-onboard-check`.
- The inspector reads tables with `lancedb` directly and prints only
  counts, versions, index names, and duplicate-key tallies.
- Tick AC 15-17 in `spec.md` in the same change; add a `docs/backlog.md`
  section for the Ask-first items left open with the evidence that
  motivates them.

**Done when:** receipts `01`, `10`, `11`, `12`, `20`, `21`, `22`,
`30`, `40` exist with the stated outcomes; the notes summary is
committed; spec ACs ticked; backlog updated.

## Rollout

Big bang in one PR. Reversible by revert. No infra. No feature flag.
No schema migration beyond creating the canonical memory table names
on first initialize or save. Operators with a half-written
`graph_relationships` table re-run `ai index` after this ships.

## Risks

- Keep-last may drop a real edge if two distinct relationships share
  an 8-hex-char id. Collapse is logged; unique keys are preserved.
- Apple Silicon users lose the MPS speedup by default. Opting in is one
  env-file line; the trade is a slower first index over an aborted one.
- Memory table rename (CLI hardcoded names vs config names) leaves any
  accidental `memory_episodic` rows unread. The explore report showed
  those tables never grew.
- Without per-write `optimize()`, a long run accumulates one fragment
  and one version per write until the 50-file maintenance and the
  post-index maintenance compact them. Query latency during a run may
  rise; the end state is compacted.
- The per-table lock serializes writes from concurrent files. Once
  `optimize()` is gone a write is milliseconds, so the semaphore-limited
  parsing and embedding stay the bottleneck. Bound: the fresh run
  `30-*` indexes at least 32 files per minute, twice the failed run's
  16 files per minute (spec Assumptions).
- Existing indexes: `document_chunks` tables that never got an FTS
  index gain the native one on next open. Tables that got a Tantivy
  index on a 0.25.x install carry `<table>.lance/_indices/fts`, which
  `list_indices()` does not report but which blocks native index
  creation on 0.38.0 and captures every FTS query on 0.25.2; the
  manager deletes that directory before creating the native index
  (`remove_legacy_fts_index`, tested on disk).

## Changelog

- 2026-09-04: initial plan from approved index-memory-reliability plan.
- 2026-09-04: spec-stage review: list/recall as the memory honesty bar;
  drop optional embeddings.md task; T2 tests require the printed graph
  error text.
- 2026-09-04: PLAN trio - files: `lancedb_manager.py`, indexing flush
  path, memory CLI/adapters, `env_resolver.py`, README. Tests: on-disk
  LanceDB collapse, graph-write status/exit, memory save/list/recall
  honesty, Darwin hatch gating. Not changing: first-run-reliability,
  retry predicates, default CPU, lock, FirstSeen, python-dotenv,
  CHANGELOG. Declined patterns remain those in the spec. TDD stubs
  materialised under per-task Tests.
- 2026-09-21: second pass after the real-corpus run failed with write
  conflicts. Added T5 (per-table lock, no per-write optimize), T6
  (native FTS on `fts_text`), T7 (real-corpus qualification with
  receipts). Files: `lancedb_manager.py`, `lancedb_schemas.py`,
  `tables.py`, `schema_manager.py`, tests, spec, backlog. Not changing:
  retry predicates, `maintenance_interval_files`, cleanup window,
  connector-based skip, cross-process lock, `uv.lock`.
- 2026-09-21: spec-stage review. Lock ownership moved from
  `LanceDBManager` to `TableManager` so open/create and index creation
  are covered; T5 now depends on T6 (its FTS visibility test needs the
  native index); ACs renumbered 9-17; AC 10 scoped to one manager with
  a create-race construction test; AC 14 uses a zero cleanup window;
  AC 15 split into write-conflict classes, attributed non-write
  failures, and a files-per-minute bound; committed notes summary
  added to T7.
- 2026-09-21: EXECUTE. The 0.38.0 gate showed `compact_files` and
  `cleanup_old_versions` need pylance there; maintenance now goes
  through `Table.optimize` on both versions.
- 2026-09-21: implementation review. Added `remove_legacy_fts_index`
  (Tantivy directory blocks native FTS on 0.38.0) with an AC 12 clause
  and on-disk test; honest create-race handling; `table_lock` required
  on the schema manager; `docs/backlog.md` section for the Ask-first
  items and defects found.
