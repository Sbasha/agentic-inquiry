# Spec: Memory field updates survive concurrent access bookkeeping

Mode: light (no risk trigger fired: the tasks are ordered steps of one
change rather than separate features, `LanceDBManager.update_by_ids` is an
additive internal method, and `MemoryStorageProtocol.update` had no caller
before this change)

- **Status:** Shipped
- **Owner:** sbasha
- **Plan:** none (task list below)
- **Constrained by:** none
- **Brief:** none
- **Discovery:** none
- **Contract:** none
- **Shape:** service

## Objective

An agent recalls memories and then changes one: it raises a memory's
importance or a fact's confidence right after `retrieve()` returned it.
The next read returns the new value, every time, and the item has one row.

`EpisodicMemory.retrieve()` and `SemanticMemory.retrieve()` record access
statistics in a background task that re-reads each hit and writes the
count back, so that write can overlap the caller's own update. Access
bookkeeping, `MemorySystem.update_importance` and
`MemorySystem.update_confidence` therefore write only the columns they
change, in one LanceDB commit per item. None of the three can revert a
field another one wrote or leave a second row for the same id.

Out of scope, tracked in [`docs/backlog.md`](../../backlog.md#memory-update-atomicity):
two overlapping accesses of one item, which can count once. `negate_memory`
and `supersede_memory` write only their columns under
[`lancedb-single-commit-upsert`](../lancedb-single-commit-upsert/spec.md).

## Acceptance Criteria

- [x] `LanceDBMemoryAdapter.update(item_id, updates)` changes only the
      named columns of the matching row, in a single LanceDB commit, and
      never deletes or inserts a row. It returns `False` when no row has
      that id. It raises `ValueError` for any key outside
      `memory.protocols.UPDATABLE_FIELDS` (identity and context fields,
      `content`, `summary`, embeddings, `metadata`), and
      `InMemoryMemoryAdapter.update` rejects the same keys.
- [x] `LanceDBMemoryAdapter.update` writes each value the way `store()`
      does: enums as their value, numpy scalars as Python numbers, and
      `None` as `""` or `0.0` on the optional text and number columns. It
      raises `ValueError` for `None` on a required column, an unknown
      tier or status, or a non-finite number, and leaves the row unchanged.
- [x] Access bookkeeping in both persistent layers (`get_by_id` with
      `update_access=True`, and the background task `retrieve()` starts)
      writes only `access_count` and `accessed_at`. An importance or
      confidence change that lands between the bookkeeping read and its
      write survives, and the item still has exactly one row.
- [x] `MemorySystem.update_importance` and `MemorySystem.update_confidence`
      write only the score, `modified_at` and `modifier_agent_id` for
      episodic and semantic items. An access recorded between the
      setter's read and its write survives. `update_importance` goes on to
      the next tier when the item left the tier it was read from.
- [x] `pyproject.toml` requires `lancedb>=0.23.0`, the first release whose
      `Table.update` reports the number of rows it updated.
- [x] `test_store_retrieve_update_delete` passes 10 consecutive runs with
      `INQUIRY_EMBEDDING_DEVICE=cpu uv run pytest -p no:randomly`.

## Tasks

1. Add `LanceDBManager.update_by_ids(table_name, ids, values) -> int`:
   one `table.update` under the per-table commit lock and write retry,
   returning rows updated.
2. Rewrite `LanceDBMemoryAdapter.update` on top of it, with the shared
   `UPDATABLE_FIELDS` allowlist.
3. Route layer access bookkeeping through `storage.update`, and add a
   layer `update_fields(item_id, updates) -> bool` for the system setters.
4. Switch `update_importance` and `update_confidence` to `update_fields`.

Verification: TDD. The adapter and layer tests in `tests/memory/` force
each interleaving deterministically by committing a second write right
after the first read. The adapter test also asserts that an update adds
exactly one table version. Running the e2e lifecycle test 10 times in a
row covers the end-to-end path.
