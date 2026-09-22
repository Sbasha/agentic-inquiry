# Backlog — open items by spec

Single index of **open** work across every spec in `docs/specs/`. Each item
names the spec, the Acceptance Criterion (where one applies), what's blocking
it, and how it gets unblocked. Closed/shipped work is **not** kept here — see
each spec's Changelog and [`product/changelog.md`](product/changelog.md).

This is the tactical **backlog**: per-instance, no pack-side source after first
install — it's yours to curate. It is distinct from the **product roadmap**
(strategy, not a work index) at [`product/roadmap.md`](product/roadmap.md).
"Roadmap" = direction; "backlog" = the work/deferral index.

Deferred acceptance criteria point here by **anchor**: a spec criterion written
`- [ ] <outcome> (deferred: <anchor>)` means `<anchor>` resolves to a heading in
this file (GitHub heading-slug rules — lowercase, spaces become hyphens). The
deferral lives here, version-controlled and greppable, not in a PR comment that
rots. See `CONVENTIONS.md` § 4 (Spec metadata contract).

## How this file is maintained

- Every spec records its own `Status:` field and `Acceptance Criteria`
  checkboxes. This file aggregates the **open** items so they're visible in one
  place — it is not the source of truth.
- When an AC closes or a spec ships, update the spec first, then **remove** the
  now-closed item here in the same change (closed work lives in the spec
  Changelog / `product/changelog.md`, not here).
- When a new spec lands with open ACs, add a section here.
- If an item here is no longer accurate against the underlying spec, trust the
  spec and fix this file.

---

## index-memory-reliability

Open items from [`specs/index-memory-reliability/spec.md`](specs/index-memory-reliability/spec.md).
None is a deferred acceptance criterion; each is an `Ask first` decision or
a defect found while qualifying and left for its own change.

- **FTS recall on raw content:** `document_chunks` has one native FTS
  index, on `fts_text`, and the chunk embedding is computed from the same
  projection. A token the projection drops (language keyword, bare
  number, single character, text past 1,000 words) is reachable by
  neither FTS nor vector search. Decide whether `fts_text` should keep
  those tokens or whether a second FTS index on `content` (which makes
  every FTS and hybrid query name its columns) is worth it.
- **Unchanged-file skip on re-run:** `ai index` passes no connector, so
  `file_states` stays empty and every run re-parses every file; re-runs
  are idempotent but not incremental. Unblocked by wiring
  `FileSystemConnector` with the metadata-store file tracker into
  `index_command`, after checking its ignore rules match the current
  filesystem discovery.
- **Repair of legacy duplicate-key rows:** tables written by the
  unserialized writer can hold several rows per `(id, project_id)`
  (198 such rows in the 2026-09-21 qualification index). `merge_insert`
  updates every copy; nothing removes the extras. A maintenance step
  that deletes all but one copy per key needs `_rowid` deletes and a
  decision on which copy wins.
- **Relationship growth on re-index:** a second `ai index` over a
  complete index adds `calls` and `imports` edges whose `target_id`
  matches no stored entity (59,548 to 66,813 distinct keys on the
  2026-09-21 qualification index; unresolved targets 296 to 4,016).
  Chunk and entity keys stay unchanged. No third run was measured, so
  whether growth converges or repeats per run is the open question.
  Find where the graph builder's resolution against pre-existing
  entities produces ids that the entity writer never stores, and make
  re-index converge.
- **`branch_expiry` chunk prune bypasses the manager:**
  `agentic_inquiry/indexing/branch_expiry.py` calls a `get_or_create_table`
  that `LanceDBManager` does not expose and deletes rows on the table
  directly, outside the per-table lock. Route it through
  `LanceDBManager.delete_by_ids`.
- **Single `optimize` per maintenance pass:** `run_maintenance` still
  runs a compaction pass and a cleanup pass, each a `Table.optimize`
  call, to keep the compaction-then-cleanup contract its tests pin. One
  call with the caller's window does the same work once.
- **`tantivy` dependency:** no code imports it after the native FTS
  switch. Remove it from `pyproject.toml` with an ADR.

<!-- Add one section per spec with open work, e.g.:

## <spec-name>

- **AC<N> (deferred: <anchor>):** <what's open> — blocked on <X>; unblocked by <Y>.

-->
