# Spec: LanceDB row replacement is one commit

- **Status:** Shipped
- **Owner:** sbasha
- **Plan:** [`plan.md`](plan.md)
- **Constrained by:** [`memory-update-atomicity`](../memory-update-atomicity/spec.md), [`index-memory-reliability`](../index-memory-reliability/spec.md)
- **Brief:** none
- **Discovery:** none
- **Contract:** none
- **Shape:** service

> **Spec contract:** this document defines what "done" means. The implementing
> PR must match this spec, or update it. Verification must be derivable from it.

## Objective

Two writers sharing a `LanceDBManager` that replace the same stored row at the
same time leave exactly one row behind, holding one writer's complete value.
This holds for MCP session persistence (`LanceDBSessionStorage.persist_session`,
keyed on `session_id`, the one production caller of `LanceDBManager.upsert()`),
for `LanceDBAdapter.upsert` (the `VectorStorageProtocol` record upsert, which
has no production caller), and for whole-row replacement of episodic and
semantic memory items (`EpisodicMemory.update(item)`,
`SemanticMemory.update(item)`).

Each of these writes is one LanceDB commit that inserts the row or updates it
in place. There is no window between a delete and an insert in which a second writer can
find the key absent and insert its own copy. Storing a memory item whose id is
already stored replaces that row.

`MemorySystem.negate_memory()` and `MemorySystem.supersede_memory()` change a
stored episodic or semantic item's status with one `update_fields()` call,
which writes only the named columns in one commit. Access statistics written
by another task between their read and their write survive, and a reader never
sees a half-negated item.

## Boundaries

### Always do

- Route every LanceDB write through the per-table commit lock and
  `_retry_lancedb_write`, as the existing `_upsert_rows` does.
- Reproduce each race with a deterministic test on a real on-disk LanceDB
  that runs the competing writer inside the commit window.

### Ask first

- Changing `upsert()` to replace absent columns with null (whole-row
  semantics) instead of leaving them as stored.
- Changing `store_batch()` from append to upsert.

### Never do

- Edit files in another session's worktree, or re-implement
  `update_by_ids` / `update_fields`; they come from memory-update-atomicity.
- Add a lock or retry layer above LanceDB to paper over a two-commit write.

## Testing Strategy

All behaviors are TDD, verified by integration tests against an on-disk
LanceDB in `tmp_path`. The concurrency tests run a competing writer at a fixed
point inside the write under test (the plan's Approach names the mechanism),
so each race reproduces on every run. Single-commit claims are also checked
directly: a lone write raises the table's `version` by exactly one.

## Acceptance Criteria

- [x] When a second `LanceDBManager.upsert()` of the same key runs to
      completion after the first upsert's first commit, the table holds
      exactly one row for that key, carrying the second writer's values.
      Holds for `key_field="id"` and `key_field="session_id"`.
- [x] A lone `LanceDBManager.upsert()` into an existing table raises the
      table's `version` by exactly one.
- [x] `LanceDBManager.upsert()` inserts records whose key is new, updates
      records whose key exists, keeps the stored value of any column a record
      omits, and collapses repeated keys within one call to the last record.
- [x] `LanceDBManager.upsert()` raises `ValueError`, and writes nothing, when
      a record's key field is missing, `None`, or `""`, when the records in
      one call do not all have the same set of fields, or when a record fails
      schema validation.
- [x] When a second `EpisodicMemory.update(item)` (and
      `SemanticMemory.update(item)`) of the same item runs to completion after
      the first update's first commit, the table holds exactly one row for
      that id, carrying the second writer's values.
- [x] A lone `EpisodicMemory.update(item)` or `SemanticMemory.update(item)`
      raises the table's `version` by exactly one; when it fails, the stored
      row is unchanged.
- [x] `LanceDBMemoryAdapter.store()` of an item whose id is already stored
      replaces that row; the table still holds one row for the id.
- [x] `negate_memory()` sets `importance` to 0.0 and `status` to `NEGATED`
      on an item in any tier. On an episodic or semantic item it does so in
      one commit without rewriting other columns: an `access_count` written by
      another task before that commit survives.
- [x] `supersede_memory()` on an episodic or semantic item sets `status` to
      `SUPERSEDED` and `superseded_by` to the new item's id without rewriting
      other columns: an `access_count` written by another task before that
      commit survives. If the old item moves to a later tier between
      supersede's read and its write, it is marked there; if it is deleted,
      supersede logs a warning and still returns the new item.

## Assumptions

- Technical: `merge_insert(...).when_matched_update_all()` updates only the
  columns present in the source and leaves the rest as stored; a source row
  whose key is null is neither matched nor inserted, and vanishes without
  error; the source columns come from the first record, so a batch with mixed
  field sets drops or nulls fields (source: probes against lancedb 0.25.2 /
  pylance 0.38.2, 2026-09-26).
- Technical: `merge_insert` updates every target row that matches a source
  key, so a key that already has duplicate rows gets the new value in each
  copy (source: `tests/database/test_lancedb_write_serialization.py::test_upsert_into_duplicated_key_updates_every_copy`).
- Technical: the commit lock is per `LanceDBManager`. Writers in different
  managers or processes (the CLI and the MCP server each build their own) are
  not serialized by it, and two concurrent `merge_insert` calls for the same
  new key can both insert (source: `agentic_inquiry/database/tables.py`
  `table_lock`; index-memory-reliability spec, Assumptions). This spec does
  not claim the cross-manager case.
- Technical: no LanceDB table schema defines `branch`, `is_active` or
  `expired_at`, so `_upsert_rows` stripping `BRANCH_INDEXING_FIELDS` drops
  nothing a table can store (source: `agentic_inquiry/models/document_chunk.py:20`,
  `agentic_inquiry/database/lancedb_schemas.py`).
- Technical: `persist_session` sends every column of the row (source:
  `agentic_inquiry/mcp/models/session.py` `to_db_record`).
- Technical: callers that store an id already present in the target table
  now replace it instead of adding a duplicate: tier promotion in
  `agentic_inquiry/memory/consolidation.py` and
  `MemorySystem.promote_to_semantic` (source: code read, 2026-09-26).
  `InMemoryMemoryAdapter.store()` already replaces by id.
- Technical: at capacity, `EpisodicMemory.store` / `SemanticMemory.store`
  evict before storing even when the id is already stored, so re-storing an
  id deletes an unrelated item and leaves `limit - 1` rows. Out of scope here
  (source: `agentic_inquiry/memory/layers/episodic.py` `store`;
  [backlog](../../backlog.md#lancedb-single-commit-upsert)).
- Technical: `mcp_sessions` has no explicit schema, so a first session with
  `description` or `log_file` unset creates null-typed columns and a later
  persist that sets either fails with `StorageError`; the stored row survives
  the failure. Pre-existing and out of scope (source: reproduced on this
  branch, 2026-09-26;
  [backlog](../../backlog.md#lancedb-single-commit-upsert)).
- Technical: `ConsolidationEngine` promotes an episodic item to semantic
  without deleting the episodic copy, so one id can be stored in two tiers.
  `negate_memory()` and `supersede_memory()` mark the first tier that holds
  the id, working, then episodic, then semantic; the other copy stays active.
  Out of scope (source: `agentic_inquiry/memory/consolidation.py`
  `promote_to_semantic`;
  [backlog](../../backlog.md#lancedb-single-commit-upsert)).
- Product: `store()` upserts by id although the `merge_insert` adds a flat
  ~8 ms per call over an append (source: user confirmation 2026-09-26).
- Process: `update_fields()` and `LanceDBManager.update_by_ids()` come from
  memory-update-atomicity, which this change is built on (source:
  `feature/memory-update-lost-write` at `f5b36af`).
