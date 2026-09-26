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

## afp-lifecycle-contract

Open items from [`specs/afp-lifecycle-contract/spec.md`](specs/afp-lifecycle-contract/spec.md).

- **Rebuild memory rows from the ledger:** deferred from the spec. The ledger
  under `INQUIRY_HOME/projects/<project_id>/records.sqlite3` keeps every
  captured observation payload, so LanceDB memory rows are rebuildable,
  but no command performs the rebuild. Unblocked by an
  `ai integration reconcile --replay` that re-stores committed capture rows
  whose memory item is missing from the bound environment.
- **Config loader warns about control variables:** `Config.load()` prints
  "Ignoring invalid environment variable INQUIRY_HOME" (and "unknown" for
  multi-segment names such as `INQUIRY_HOOK_DEADLINE_SECONDS`) because the
  environment-override parser has no allowlist for the documented control
  variables (`agentic_inquiry/config.py` around line 1838). Operator-visible
  noise on every command; the lifecycle contract keeps its own stderr silent
  with a `NullHandler`, so this is a separate fix.
- **`hybrid_search` passes a raw full-text query:** `agentic_inquiry/database/query_builder.py`
  sanitises the FTS query on the `fts_search` path (primary branch and, after this
  change, the stale-table retry) but `hybrid_search` calls `.text(query)` unsanitised
  on both of its branches. The hook path never reaches it; the MCP and CLI search
  paths do. Unblocked by routing every `.text(...)` call through `_fts_sanitizer`.
- **Authenticated non-loopback MCP:** AC30 makes the MCP http and sse transports
  loopback-only because `/mcp` is exempt from the REST API-key middleware and the
  MCP server has no authentication of its own, which withdraws the containerised
  and orchestrated MCP recipes at 0.3.0. Unblocked by an MCP-side bearer-token
  check (or the middleware covering `/mcp`) so `bind_host(..., auth_enabled=True)`
  can admit a non-loopback bind for the transports too.
- **Release note for 0.3.0:** `docs/CONVENTIONS.md` asks for a `CHANGELOG.md`
  entry on user-visible changes while the owner's standing rule forbids hand
  edits to changelog files, so this change leaves the file untouched. The
  owner settles it: write the entry, or amend the convention through
  `update-conventions`.
- **Framing in the standalone skills:** `/ai:memory` and `/ai:search` read the
  same storage namespace the lifecycle contract commits into, and render
  recalled content without the AC21 frames. Unblocked by the standalone
  plugin migration, which should adopt `render_text`.
- **Native qualification on Codex and Pi:** the Claude Code replay through the
  AFP bridge is recorded in
  [`specs/afp-lifecycle-contract/notes/afp-pack-journey.md`](specs/afp-lifecycle-contract/notes/afp-pack-journey.md).
  Live Codex and Pi sessions, including native compaction, stay deferred.
  The pack's `native-qualification` field records a run once it exists.
- **Standalone Claude plugin as a translator:** the scripts under
  `extensions/claude/ai/hooks/scripts/` import the package from the ambient
  interpreter, start the REST server on demand and inject a prompt on every
  Stop. Unblocked by a spec that routes them through
  `ai integration hook --client claude-code` with `owner: standalone` and
  removes the server start and the prompt hooks.

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

## memory-update-atomicity

Open items from [`specs/memory-update-atomicity/spec.md`](specs/memory-update-atomicity/spec.md).
None is a deferred acceptance criterion; each is a write path the spec
leaves out.

- **Lost access increments:** access bookkeeping reads `access_count` and
  writes back the incremented value, so two accesses of one item that
  overlap count once. Unblocked by an increment expressed in the update
  itself (`values_sql` `access_count + 1`), which the storage protocol
  cannot express today.

## lancedb-single-commit-upsert

Open items from [`specs/lancedb-single-commit-upsert/spec.md`](specs/lancedb-single-commit-upsert/spec.md).
None is a deferred acceptance criterion; each is a defect the spec found and
leaves out.

- **Eviction on re-store:** at capacity, `EpisodicMemory.store` and
  `SemanticMemory.store` evict the oldest item before storing, even when the
  item's id is already stored and the store only replaces it. Re-promoting an
  id (`consolidation.py`, `MemorySystem.promote_to_semantic`) then deletes an
  unrelated memory and leaves the tier one below its limit. Unblocked by
  skipping eviction when the id is already stored, at the cost of a lookup
  per store.
- **One id in two tiers:** `ConsolidationEngine.promote_to_semantic` stores
  an episodic item in semantic memory and keeps the episodic copy.
  `negate_memory` and `supersede_memory` mark only the first tier that holds
  the id, so the semantic copy stays active and keeps showing up in
  retrieval. Needs a decision: delete the source copy on promotion, or mark
  every tier that holds the id.
- **Working-memory writes resurrect removed items:** `MemorySystem._write_fields`
  stores a working item back unconditionally. If consolidation removed it
  from working memory while supersede awaited the new item's embedding, the
  store re-inserts it and, at capacity, evicts an unrelated item. Unblocked
  by a working-memory presence check that does not count as an access.
- **Inferred `mcp_sessions` schema:** the table is created from the first
  session's record, so a first session with `description` or `log_file`
  unset makes those columns null-typed, and every later persist that sets
  either fails with `StorageError`. Unblocked by creating `mcp_sessions` from
  an explicit schema.

<!-- Add one section per spec with open work, e.g.:

## <spec-name>

- **AC<N> (deferred: <anchor>):** <what's open> — blocked on <X>; unblocked by <Y>.

-->
