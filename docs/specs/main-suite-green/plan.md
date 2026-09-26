# Plan: Main test suite green

- **Spec:** [`spec.md`](spec.md)

## Approach

Group the failing set by root cause, not by test. For each group, reproduce it,
decide whether the product or the test is wrong, and fix that side once. Where
a test's `MagicMock` has drifted from the object it stands in for, replace it
with the real collaborator; several product defects only show up that way,
because the mocks returned what the tests expected instead of what the product
does.

## Design decisions

- **Session tests use a real LanceDB.** A shared `lancedb_storage` fixture in
  `tests/mcp/conftest.py` builds a `StorageFacade` from a registry-shaped
  `StorageConfig` over `tmp_path`. Fault-path tests patch one method of the real
  manager to raise, instead of mocking the whole manager.
- **Filter ASTs pass through the LanceDB providers.** `LanceDBVectorProvider.query`
  and `LanceDBGraphProvider.query_relationships` hand filters and `project_id`
  to `LanceDBManager.advanced_filter`, which already combines either form with
  the project scope. The `relationship_type` to `type` key shim goes; its only
  caller now uses the schema column.
- **Memory writes are atomic and serialised.** A layer writes an item over its
  stored copy with the storage adapter's `replace()`, which on LanceDB is one
  `merge_insert` commit (`LanceDBManager.upsert`), so a cancelled or failed
  write never leaves the item missing. `EpisodicMemory` and `SemanticMemory`
  each hold an `asyncio.Lock` around updates, deletes, evictions and
  access-stat refreshes; `modify(item_id, change)` re-reads, mutates and
  replaces an item under that lock, and `MemorySystem` uses it for importance,
  confidence, negation and supersede, so no caller writes back a copy it read
  earlier. Background refreshes are tracked, coalesced per item (repeat
  retrieves add to a pending access count instead of queueing more work), log
  failures at warning, and are awaited by `MemorySystem.shutdown` through
  `wait_for_background_writes()`.
- **Model loads are serialised process-wide.** transformers builds models under
  global meta-device patching; two overlapping loads leave every later load in
  the process failing. `SentenceTransformerEmbedder` loads under one
  module-level lock.
- **Wall-clock budgets are opt-in.** A `perf` marker, registered in
  `tests/conftest.py`, is skipped unless `INQUIRY_PERF_TESTS=1`; every test that
  asserts a wall-clock budget carries it. Hypothesis runs with a suite-wide
  profile that has no per-example deadline: the property tests assert
  behaviour, and a deadline only fails them on a loaded machine.
- **Cohere is removed, not tolerated.** The charter rules out optional hosted
  paths, so the reranker, its registration and its enum value go.

## Risks

- A LanceDB `mcp_sessions` table created before this change with a
  `null`-typed `description` or `log_file` column keeps rejecting sessions that
  set those fields. The persist error names the columns and tells the user to
  delete the table (sessions are recreated on demand).
- Configs with `reranker_type: cohere` now fail validation. The commit carries
  a `BREAKING CHANGE` footer so the generated changelog records it.
- The LanceDB cross-encoder and ColBERT rerankers load their models inside
  lancedb, outside the embedder's load lock.
- The memory-layer lock is per process; concurrent writers in separate
  processes are not serialised.
- All writes within one memory layer share one lock. Memory writes are
  low-rate agent actions, so per-item locking was not added.
- `LanceDBManager.upsert` (used by session persistence and the generic
  LanceDB adapter) now commits through `merge_insert` instead of delete then
  insert.
