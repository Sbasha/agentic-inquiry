# Plan: LanceDB row replacement is one commit

- **Spec:** [`spec.md`](spec.md)
- **Status:** Done

> **Plan contract:** this is the implementation strategy. Unlike the spec, this
> document is allowed to change as you learn.

## Approach

Reproduce first, then fix. A test helper in `tests/utils/commit_hook.py` wraps
`LanceDBManager._locked`, the context manager every write to an existing table
commits inside, and runs a callback on entry or on normal exit of the commit
lock, skipping the callback's own writes. Table creation does not pass through
`_locked`, so tests seed the table before arming the hook. T1 uses it to show `upsert()` leaving
two rows for one key; T2 rewrites `upsert()` as record checks plus one call to
the existing `_upsert_rows` merge, and brings the in-memory test manager's
`upsert` in line. T3 reproduces the duplicate from `EpisodicMemory.update(item)`,
then makes `LanceDBMemoryAdapter.store()` write through `upsert()` so
`update(item)` is one `store()` call. T4, after rebasing onto
memory-update-atomicity, turns negate and supersede into single
`update_fields()` writes. The riskiest part is T2's semantic shift for records
that omit columns; the spec pins it as an acceptance criterion.

## Constraints

- memory-update-atomicity owns `update_by_ids`, `update_fields` and the
  adapter's field-update allowlist. T4 builds on them and does not redefine
  them.
- index-memory-reliability: concurrent writes to one table go through the
  per-table lock and write retry; this plan adds no new lock.
- AGENTS.md: async at the I/O boundary; parameterized filters only.

## Construction tests

**Integration tests:** `tests/database/test_lancedb_upsert_atomicity.py` (T1,
T2), `tests/mcp/services/test_lancedb_session_storage_disk.py` (T2) and
`tests/memory/test_memory_row_replace_atomicity.py` (T3, T4), all on on-disk
LanceDB, seeded before the hook is armed.

**Manual verification:** none; no user-invoked artifact changes beyond the
methods under test.

## Design (LLD)

### Design decisions

- `upsert()` delegates to `_upsert_rows(table, data, key_column=key_field)`,
  which writes through
  `merge_insert(key).when_matched_update_all().when_not_matched_insert_all()`
  and already validates records, collapses repeated keys, creates the table
  on first write, and holds the commit lock with write retry.
  Traces to: AC1-AC3.
- `upsert()` rejects a record whose key is missing, `None` or `""` (checked
  with `is None` / `== ""`, not falsiness), and rejects a call whose records
  have different field sets. `merge_insert` silently drops null-key rows and
  takes its columns from the first record, so either input would lose data.
  It also runs schema validation itself before `_upsert_rows`, whose
  `try` would wrap a validation error as `StorageError`, so every
  invalid-record error is a `ValueError`, as `VectorStorageProtocol.upsert`
  (`agentic_inquiry/database/protocols.py`) documents. Traces to: AC4.
- `LanceDBMemoryAdapter.store()` calls `self._manager.upsert(table, [row])`
  instead of `add_rows`. Storing an existing id replaces it, as
  `InMemoryMemoryAdapter.store()` already does; `MemoryStorageProtocol.store`
  documents that. The layers' `update(item)` becomes one `store()`.
  Traces to: AC5-AC7.
- `negate_memory()` reads the item once per tier to find it and its context
  agent id, then writes `importance`, `status`, `modified_at` and
  `modifier_agent_id` with one `update_fields()` call. A working-memory item
  gets the same four fields set in process and is stored back. `supersede_memory()` writes `status`, `superseded_by`
  and `modified_at` with one `update_fields()` call. Traces to: AC8, AC9.

### Failure, edge cases & resilience

- A key that already has duplicate rows from an earlier race: `merge_insert`
  updates every copy.
- `update_fields()` returns `False` when the item was deleted after the read:
  negate moves on to the next tier; supersede logs a warning and returns the
  new item, which was already stored.

### Quality attributes (NFRs)

- `store()` runs a `merge_insert` join on `id` instead of an append.
  Single-item `store()` latency, 30 calls each on an on-disk table:

  | Rows | Append p50 / p90 | Upsert p50 / p90 |
  |---|---|---|
  | 1k | 4.3 / 5.4 ms | 12.3 / 20.3 ms |
  | 10k | 3.5 / 4.5 ms | 11.5 / 15.5 ms |

  The overhead is flat in table size; the user accepted it (spec,
  Assumptions).

## Tasks

### T1: The upsert race is reproduced

**Mode:** TDD (integration, on-disk LanceDB)
**Depends on:** none
**Touches:** tests/utils/commit_hook.py, tests/database/test_lancedb_upsert_atomicity.py
**Tests:**
- `test_concurrent_upsert_leaves_one_row[id]` and `[session_id]`: seed a row,
  arm the hook to run a second `upsert()` of the same key with
  `state="second"` after the first writer's first lock exit, run the first
  `upsert()` with `state="first"`. Assert one row for the key with
  `state == "second"`.
**Approach:** `commit_hook(manager, on_enter=None, on_exit=None)` async context
manager patches `manager._locked` on the instance and restores it on exit.
**Done when:** the test fails on `main` with two rows for the key.

### T2: upsert is one commit

**Mode:** TDD (integration, on-disk LanceDB)
**Depends on:** T1
**Touches:** agentic_inquiry/database/lancedb_manager.py, tests/utils/in_memory_lancedb_manager.py, tests/database/test_lancedb_upsert_atomicity.py, tests/mcp/services/test_lancedb_session_storage_disk.py
**Tests:**
- T1's tests pass.
- `test_upsert_is_one_commit`: seeded table; one `upsert()` of an existing
  key raises `table.version` by exactly one.
- `test_upsert_inserts_new_and_updates_existing`: one call with a new key and
  an existing key; both land, one row each.
- `test_upsert_keeps_columns_a_record_omits`: seed `{id, state, note}`, upsert
  `{id, state}`; `note` keeps its value.
- `test_upsert_collapses_repeated_keys_to_last`.
- `test_upsert_rejects_record_without_key` parametrized over missing, `None`,
  `""`: `ValueError` naming the key field; row count and version unchanged.
- `test_upsert_rejects_mixed_field_sets` in both record orders: `ValueError`;
  nothing written.
- `test_persist_changed_session_keeps_one_row`: `LanceDBSessionStorage`
  persists a session, persists it again changed, and `load_session` reads the
  change back from the one row for the id.
**Approach:** Replace the body of `upsert()` with the two checks and a call to
`_upsert_rows`; rewrite its docstring. Make the in-memory manager's `upsert`
apply the same checks and keep omitted columns.
**Done when:** listed tests green; `tests/database` and `tests/mcp` show no new
failures against `main`.

### T3: Memory whole-row replace is one commit

**Mode:** TDD (integration, on-disk LanceDB)
**Depends on:** T2
**Touches:** agentic_inquiry/memory/adapters/lancedb_adapter.py, agentic_inquiry/memory/protocols.py, agentic_inquiry/memory/layers/episodic.py, agentic_inquiry/memory/layers/semantic.py, tests/memory/test_memory_row_replace_atomicity.py
**Tests:**
- `test_concurrent_update_leaves_one_row[episodic|semantic]`: store an item,
  arm the hook to run a second layer `update()` with `importance=0.2` after the
  first writer's first lock exit, run the first `update()` with
  `importance=0.9`. One row for the id, importance 0.2. Seen red first.
- `test_update_is_one_commit[episodic|semantic]`: version rises by one.
- `test_failed_update_leaves_row_unchanged[episodic|semantic]`: an `update()`
  whose write fails (wrong-dimension embedding) raises and the stored row
  still has its original content and importance.
- `test_store_existing_id_replaces_row`: adapter `store()` twice with one id
  and different content; one row, second content.
**Approach:** `store()` → `self._manager.upsert(self._table_name, [row])`;
layer `update(item)` → `self._storage.store(item, vector)`; fix docstrings
that describe delete + store or append.
**Done when:** listed tests green; latency recorded above;
`tests/memory` shows no new failures against `main`.

### T4: negate and supersede write only their columns

**Mode:** TDD (integration, on-disk LanceDB)
**Depends on:** T3, memory-update-atomicity task 3 (layer `update_fields`)
**Touches:** agentic_inquiry/memory/system.py, docs/backlog.md, docs/specs/memory-update-atomicity/spec.md, tests/memory/test_memory_row_replace_atomicity.py, tests/memory/test_negative_truths.py
**Tests:**
- `test_negate_keeps_concurrent_access_count[episodic|semantic]` and
  `test_supersede_keeps_concurrent_access_count[episodic|semantic]`: on a real
  `MemorySystem`, arm the hook to set `access_count` to one more than its
  stored value, through `update_by_ids`, before every lock entry on the item's
  table, counting the writes that hit a row. Afterwards `access_count` equals
  that count, `status` is `NEGATED` (importance 0.0) or `SUPERSEDED` (with
  `superseded_by` set to the returned item's id). Seen red on the rebased
  branch before the change.
- `test_negate_working_item`: a working-memory item ends with importance 0.0
  and status `NEGATED`.
- `test_supersede_returns_new_item_when_old_deleted`: delete the old item
  after supersede's read (hook on the layer's `get_by_id`); supersede returns
  the new item and logs a warning naming the old id (`caplog`).
- `test_negate_follows_item_promoted_mid_call`,
  `test_negate_item_deleted_mid_call_returns_false` and
  `test_supersede_follows_item_promoted_mid_call`: the item moves to semantic,
  or is deleted, right after the episodic read.
**Approach:** Add `MemorySystem._read_tier()` and `_write_fields()` (one
per-tier read without access bookkeeping, one per-tier field write) and use
them in `update_importance`, `negate_memory` and `supersede_memory`. Negate
drops its call into `update_importance` and its re-fetch; negate and
supersede move on to later tiers when the item moved mid-call, and warn when
it is gone. Remove the mock negate test in `test_negative_truths.py`, which
the on-disk tests cover. Remove the `docs/backlog.md` entry for whole-row
memory writes, and the matching out-of-scope sentence in the
memory-update-atomicity spec.
**Done when:** listed tests green; `tests/memory` shows no new failures
against the rebased base.
