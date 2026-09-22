# Spec: Index and memory write honesty

- **Status:** Shipped
- **Owner:** sbasha
- **Plan:** [`plan.md`](plan.md)
- **Constrained by:** none
- **Brief:** none
- **Discovery:** none
- **Contract:** none
- **Shape:** mixed

Mode: full (graph write path, memory CLI honesty, operator-facing hatch copy,
LanceDB write serialization and FTS index shape).

## Objective

An operator who indexes a project into a local LanceDB environment, then
saves memories against that same environment, gets one of two honest
outcomes from `agv index`: the graph-relationship write finishes, or the
command exits 1 with a message that names the graph write failure (even
when document chunks already exist). `agv memory save` exits 0 only when
that memory can be listed or recalled for the same project afterward.
On Darwin, when `AGV_EMBEDDING_DEVICE` is unset, `agv index` and
`agv memory save` print one stderr line pointing at the CPU hatch in
`.agv/envs/<name>/.env` before the embedding model loads.

Indexing a real repository of at least 1,400 files into a local LanceDB
environment exits 0 with no write-conflict failures. Writes, index
creation, and maintenance issued through `LanceDBManager` on one table
from one process never race each other. A row is durable and visible to
a fresh process, to filters, and to full-text search as soon as the
write call returns. `document_chunks`
carries one native FTS index on `fts_text`, the chunk's search
projection (identifiers with their camelCase and snake_case splits;
language keywords, bare numbers, single characters, and text past 1,000
words are not in it), so full-text and hybrid search work on the LanceDB
version `uv tool install .` resolves today (0.38.0) as well as the
locked development version (0.25.2). The chunk embedding is computed
from the same projection, so a token that the projection drops is
reachable by neither FTS nor vector search; that recall question is an
open item in `docs/backlog.md`. Re-running `agv index` over an index
left by a failed or interrupted run completes and adds no duplicate
keys.

## Boundaries

The three-tier guard that keeps an implementing agent inside the lines.
*Always do* applies without asking; *Ask first* requires human sign-off
before proceeding; *Never do* is a hard rule, even under time pressure.

### Always do

- Collapse duplicate merge keys in `_upsert_rows` before `merge_insert`
  by `(id, project_id)` (or the key columns that call site passed); keep
  the last row; log how many rows were collapsed.
- Treat a failed graph-relationship write as an index failure: status is
  not `completed`, `agv index` exits 1, and the printed result names the
  graph write failure. Chunk rows already written stay on disk.
- Exit `agv memory save` with code 0 only after a read-back shows the
  stored row for that project. Print the memory id, summary, importance,
  and tier on success.
- Exit `agv memory save` with code 1, and do not print `Memory saved:`,
  when importance is below 0.7 (working memory only) or when the row
  cannot be read back.
- On Darwin, if `AGV_EMBEDDING_DEVICE` is unset, print one stderr line
  naming the hatch file (`.agv/envs/<name>/.env`) before constructing
  the embedder. Leave the hatch line commented in new env files.
- Serialize writes, index creation, compaction, and version cleanup per
  table with one in-process `asyncio.Lock` per table name, owned by
  `TableManager` and used by `LanceDBManager`. Once a table is open,
  writes to different tables may run concurrently. Lock order: the
  per-table lock is outer; `TableManager._lock` (cache dictionary and
  open/create) is inner and never held while waiting for a per-table
  lock.
- Return from a write once LanceDB has committed it. Do not call
  `optimize()`, `compact_files()`, or `cleanup_old_versions()` on the
  per-write path. Keep the retry policy for cross-process conflicts.
- Run compaction and version cleanup through `Table.optimize`, the one
  maintenance entry point that works on lancedb 0.25.2 and 0.38.0.
- Create FTS indexes with native LanceDB FTS on one column per index.
  `document_chunks` indexes `fts_text` only. Before creating one, delete
  a Tantivy-era `<table>.lance/_indices/fts` directory if present; it
  holds no row data and blocks or captures native FTS.
- Keep the qualification corpus, index, logs, and receipts private under
  `~/.agv/qualification/`. Receipts hold counts, hashes, exit codes, and
  error-class tallies, never file contents or corpus paths beyond the
  root.

### Ask first

- Uncomment `AGV_EMBEDDING_DEVICE=cpu` by default on Mac.
- Add a cross-process LanceDB lock (file lock, lock manager package).
- Change `maintenance_interval_files` or the 5-minute version-cleanup
  window.
- Repair duplicate-key rows that an earlier, unserialized writer left in
  an existing table.
- Pass a `FileSystemConnector` with hash-based change detection from
  `agv index` so unchanged files are skipped on re-run.
- Opt `merge_insert` into LanceDB FirstSeen (or any database-side silent
  drop) without collapsing duplicates in our writer first.
- Change persist thresholds (episodic at 0.7, semantic at 0.9).
- Add a `--session-only` flag that lets working-memory writes exit 0.

### Never do

- Add a new top-level dependency (including `python-dotenv`).
- Add a new top-level package or a LanceDB lock manager.
- Force CPU embeddings on every Mac.
- Amend `docs/specs/first-run-reliability/` or reopen its four shipped
  decisions (onboard warning, index exit on chunks, retry filter, env
  file load rules).
- Expand Salesforce indexer coverage, convert `/agv:onboard` to a Python
  explorer, convert Gemini or Codex mirrors, or hand-edit `CHANGELOG.md`.

## Testing Strategy

- Duplicate-key collapse in `_upsert_rows`, index status and exit code
  when a graph write fails, and `agv memory save` exit codes (persisted
  row vs missing row vs working-memory): **TDD**. Each is a compressible
  invariant. Storage-layer cases run against on-disk LanceDB.
- CLI using config table names (`memory_episodic_medium` /
  `memory_semantic_high` defaults), Darwin hint gated on unset device,
  hatch line still commented in LocalSetup, and README upgrade/hatch
  paragraph: **goal-based check** (`grep` / file exists).
- `agv memory save -i 0.85 --project <id>` then `agv memory list
  --project <id>` on a temp LanceDB env: **visual / manual QA** of the
  built CLI.
- Same-table write serialization, no-`optimize()` visibility, native
  FTS index on `fts_text`, maintenance excluded from in-flight writes:
  **TDD** against on-disk LanceDB. The storage test subset also runs
  under lancedb 0.38.0 in an isolated environment (**goal-based
  check**), because that is what `uv tool install .` resolves.
- Full `agv index` of the supplied repository into the real partial
  index, a fresh-process `agv status` and `agv search`, an interrupted
  run followed by a completing re-run, and one search-to-source journey:
  **visual / manual QA** with receipts under `~/.agv/qualification/`.

## Acceptance Criteria

- [x] Given a `graph_relationships` batch with two rows that share
      `(id, project_id)` and a later distinct payload on the second row,
      `_upsert_rows` completes and the table holds one row for that key
      whose payload matches the last input row. Unique keys in the same
      batch remain one row each.
- [x] Errors whose text does not contain `commit conflict` or `Retryable`
      (including `Ambiguous merge inserts`) are not retried. When
      `add_graph_relationships` still fails after collapse, the index
      result `status` is not `completed`. `exit_code_for_index_result`
      returns 1 even if `chunks_created > 0`. `agv index` prints a
      message that names the graph write failure.
- [x] Save, list, and recall share
      `config.memory.episodic_memory.table_name` and
      `config.memory.semantic_memory.table_name` (defaults
      `memory_episodic_medium` and `memory_semantic_high`). After a
      successful save, that table exists on disk under the LanceDB
      environment directory.
- [x] Given importance `>= 0.7` and a LanceDB backend, `agv memory save`
      exits 0 only if a subsequent `agv memory list --project <id>` or
      `agv memory recall --project <id>` returns that memory id.
      Otherwise it exits 1 and does not print `Memory saved:`.
- [x] Given importance `< 0.7`, `agv memory save` exits 1, states that
      the write is session-only and not persisted, and does not print
      `Memory saved:`.
- [x] `agv memory save --project <id>` stores that project id on the
      row. `agv memory list --project <id>` and `agv memory recall
      --project <id>` filter to that project.
- [x] On Darwin with `AGV_EMBEDDING_DEVICE` unset, `agv index` and
      `agv memory save` print one stderr line pointing at
      `.agv/envs/<name>/.env` and `AGV_EMBEDDING_DEVICE=cpu` before
      embedder construction. With the variable set, they do not print
      that line. New env files still contain a commented
      `AGV_EMBEDDING_DEVICE=cpu` line.
- [x] README documents reinstalling the global `agv` with
      `uv tool install . --reinstall` so the env-file loader is on
      PATH, then uncommenting `AGV_EMBEDDING_DEVICE=cpu` in
      `.agv/envs/<name>/.env` if Metal/MPS aborts.
- [x] Given 16 concurrent `add_graph_relationships` calls on one on-disk
      table, eight of which carry the same 300 new keys, every call
      returns without error, no retryable-conflict retry is logged, and
      the table holds exactly one row per distinct key afterwards. The
      same holds for `add_document_chunks` and `add_graph_entities`.
- [x] Given one manager whose table cache was invalidated after the
      table was created, 16 concurrent writes to `document_chunks` all
      return without error, no index-creation warning is logged, and the
      table ends with one vector index and one FTS index. Two managers
      or two processes on the same directory are covered only by the
      retry policy; when two managers race to create a table, the one
      that loses the race still writes its rows.
- [x] After `add_document_chunks` returns, a second `lancedb.connect` on
      the same directory counts the new row, `advanced_filter` on the
      same manager returns it, and `fts_search` for a token that occurs
      only in that row returns it.
- [x] A new `document_chunks` table has exactly one FTS index and its
      columns are `("fts_text",)`. Opening an existing `document_chunks`
      table that has a vector index but no FTS index creates that same
      index. Opening a `document_chunks` table that carries
      `<table>.lance/_indices/fts` removes that directory, creates the
      native `fts_text` index, and `fts_search` returns a row written
      after the upgrade. `fts_search` and `hybrid_search` return a row
      for an identifier fragment that appears in `fts_text` only as a
      camelCase split, on lancedb 0.25.2 and 0.38.0.
- [x] Given a table that already holds two rows with the same
      `(id, project_id)`, `_upsert_rows` of one row for that key returns
      without error and every stored copy carries the new payload.
- [x] `run_maintenance(cleanup_older_than=timedelta(0))` on a table
      while 16 writes to that table are in flight completes without
      error, every write completes without error, no retryable-conflict
      retry is logged, and the table holds every written row afterwards.
- [x] `agv index <corpus>` against the real partial index (branch code,
      lancedb 0.38.0) exits 0 and its `error.log` contains zero
      occurrences of `Retryable commit conflict`, `Ambiguous merge
      inserts`, and `Object at location`; any file it reports failed has
      a non-write cause named in the receipt. The uninterrupted fresh
      run of the same corpus indexes at least 32 files per minute, twice
      the failed run's rate. A fresh `agv status`
      process reports counts equal to the on-disk row counts, and a
      fresh `agv search` process returns results with `file_path` values
      that exist in the corpus. Receipts record the command, exit code,
      wall-clock, stdout and stderr hashes, reported summary, and
      error-class tallies; a redacted summary is committed under
      `notes/`.
- [x] A second `agv index` of the same corpus over the same index exits
      0; the number of distinct `(id, project_id)` keys in
      `document_chunks` and `graph_entities` is unchanged, and the count
      of duplicate-key rows in every table does not grow.
      `graph_relationships` may gain keys on a re-run (the graph builder
      resolves against the entities the first run stored; recorded in
      `docs/backlog.md`). An `agv index` run killed with SIGTERM mid-way,
      followed by a full re-run, ends with the same distinct chunk and
      entity key counts as the uninterrupted run.
- [x] One `agv search` query on the qualified index returns a result
      whose `file_path` and line range point at a corpus file that
      contains the returned content; the receipt records the query, the
      returned `file_path`, line range, and SHA-256 of that corpus file.

## Assumptions

- Technical: `add_graph_relationships` upserts on `["id", "project_id"]`
  via `merge_insert`; retry matches only `commit conflict` / `Retryable`
  (source: `agent_vault/database/lancedb_manager.py`).
- Technical: relationship ids are a deterministic `edge_` + 8-hex-char
  hash of `source_id:target_id:type`; the pending-relationship queue
  allows duplicate entries (source: `agent_vault/indexing/graph_builder.py`;
  `tests/indexing/test_relationship_queue_manager.py`).
- Technical: relationship batch commit logs the error and returns
  `False` without failing the index; pipeline flush does not fail the
  operation on relationship flush errors (source:
  `agent_vault/indexing/relationship_batch_processor.py`;
  `agent_vault/indexing/pipeline.py`).
- Technical: LanceDB `merge_insert` fails closed on duplicate source
  join keys by default; Python 0.25.2 docs do not document
  `source_dedupe_behavior` on `LanceMergeInsertBuilder` (source:
  https://lancedb.github.io/lancedb/python/python/;
  https://github.com/lance-format/lance/pull/7296).
- Technical: the pipeline runs up to `processing_semaphore_limit` (20)
  files concurrently; each file's chunk and entity upsert ends with
  `table.optimize()` (compaction, 7-day version prune, index rebuild),
  and `run_maintenance` runs every 50 files while other files are still
  writing. On the supplied corpus this produced 752 upsert failures
  after five retries (`CreateIndex`/`Rewrite` preempted by a concurrent
  `CreateIndex`/`Rewrite`), `Object at location ... not found` reads of
  files pruned by concurrent cleanup, and 198 duplicate-key rows in
  `graph_relationships` because two concurrent `merge_insert` calls for
  the same new key both take the not-matched branch (source: the
  failed run's `error.log`, tallied in receipt
  `00-real-partial-index-inspect` and the baseline receipt `01-*` under
  `~/.agv/qualification/index-durability-20260921/receipts/`;
  `agent_vault/database/lancedb_manager.py` `_flush_table`;
  `agent_vault/indexing/pipeline.py`; synthetic probe on 0.25.2 and
  0.38.0, 2026-09-21).
- Technical: `merge_insert` against a target that already holds two
  rows for one key does not raise; both copies take the new payload
  (source: probe against a clone of the real `graph_relationships`
  table on 0.38.0, 2026-09-21; construction test on 0.25.2).
- Technical: `fts_text` for code chunks is built from element names,
  imports, and identifiers with camelCase/snake_case splits, minus
  language keywords, bare numbers, and single characters, capped at
  1,000 words; document chunks use `_generate_fts_text`; plain text uses
  the content itself (source:
  `agent_vault/parsers/implementations/unified_code.py`,
  `document.py`, `fallback_text.py`). The chunk embedding text is
  `fts_text or content` (source:
  `agent_vault/indexing/schema_processor.py`,
  `agent_vault/indexing/document_processor.py`).
- Technical: re-running `agv index` over a complete index leaves chunk
  and entity keys unchanged but adds `calls` and `imports` relationship
  keys whose `target_id` matches no stored entity (receipt `20-*`:
  59,548 to 66,813 distinct relationship keys, unresolved targets 296
  to 4,016). The graph builder's second pass resolves against entities
  already on disk and emits edges the first run did not; the write
  layer stores them once each. Not introduced by this change (source:
  receipts `10-*`, `20-*`, `inspect_rels` under
  `~/.agv/qualification/index-durability-20260921/`).
- Technical: the failed run indexed 1,230 files between 15:16 and
  16:32 on 2026-09-21, about 16 files per minute, with `optimize()` on
  every write (source: `main.log` timestamps of that run, tallied in
  receipt `00-real-partial-index-inspect`).
- Technical: LanceDB commits on return from `add` / `merge_insert`; a
  fresh connection sees the new version; native FTS and vector queries
  scan rows written after the index was built. `optimize()` is not
  needed for visibility (source: probe on 0.25.2 and 0.38.0,
  2026-09-21).
- Technical: on lancedb 0.38.0, `Table.compact_files()` and
  `Table.cleanup_old_versions()` raise `The lance library is required`
  (pylance is no longer bundled), so `run_maintenance` never compacted
  or pruned on the installed tool and the failed run's tables reached
  7,808 versions; `Table.optimize(cleanup_older_than=...)` works on
  both versions (source: probe on 0.25.2 and 0.38.0, 2026-09-21;
  receipt `00-real-partial-index-inspect`).
- Technical: a Tantivy-era `<table>.lance/_indices/fts` directory is
  invisible to `list_indices()`; on 0.38.0 `create_fts_index` refuses
  to build a native index while it exists and every FTS query raises;
  on 0.25.2 every FTS query is routed to the stale index. The manager
  deletes that directory before creating the native index (source:
  `lancedb/table.py` `_ensure_no_legacy_fts_index` in 0.38.0;
  `lancedb/query.py` in 0.25.2).
- Technical: `tantivy` stays in `pyproject.toml` for now; no code path
  imports it after this change, and removing a dependency is its own
  change with an ADR (recorded in `docs/backlog.md`).
- Technical: `create_fts_index(columns, use_tantivy=True)` raises
  `Tantivy-based FTS has been removed` on lancedb 0.38.0, which
  `uv tool install .` resolved on 2026-09-04; native FTS accepts one
  column per index on both versions (source: `lancedb/table.py` in both
  versions).
- Technical: `agv index` passes no connector, so `file_states` stays
  empty and every run re-parses every file; re-runs are idempotent
  through deterministic ids and `merge_insert` (source:
  `agent_vault/cli/index.py`; `agent_vault/indexing/pipeline.py`;
  `metadata.db` of the real partial index).
- Technical: `agv memory save` prints `Memory saved:` after `store()`
  with no read-back; CLI and `MemorySystem` hardcode `memory_episodic`
  / `memory_semantic`; config defaults are `memory_episodic_medium` /
  `memory_semantic_high`; adapter `initialize()` only connects (source:
  `agent_vault/cli/memory.py`; `agent_vault/memory/system.py`;
  `agent_vault/config.py`; `agent_vault/memory/adapters/lancedb_adapter.py`).
- Technical: importance `>= 0.9` is semantic, `>= 0.7` is episodic,
  otherwise working memory (source: `agent_vault/memory/system.py`).
- Product: keep-last collapse in our writer; verify-on-save for memory;
  Darwin hatch hint before embedder load; no default CPU; no lock
  manager; no LanceDB FirstSeen (source: user confirmation 2026-09-04
  via approved plan).
- Process: do not amend `docs/specs/first-run-reliability/`; Gemini and
  Codex mirrors, Salesforce indexer coverage, Python onboard explorer,
  and hand-edited `CHANGELOG.md` stay out of scope (source: user
  confirmation 2026-09-04 via approved plan).

## Declined patterns

Tempted to enable LanceDB FirstSeen; declining - the Python API does not
document it, and the database would drop edges with no log. Tempted to
force CPU embeddings on Darwin; declining - 4-8x slower, the hatch stays
commented. Tempted to add a cross-process LanceDB lock manager; declining -
this failure is duplicate merge keys, not a retryable commit conflict.
Tempted to add `python-dotenv` or a `--session-only` success path;
declining - no new dependency, and working-memory CLI writes are not
success. Tempted to add a file-based cross-process lock; declining -
every observed conflict came from one process racing itself, and the
retry policy already covers rare cross-process commits. Tempted to keep
`optimize()` per write behind a flag; declining - it is neither needed
for durability nor for visibility, and it is the conflict source.
Tempted to widen the retry budget; declining - retries were masking a
design fault, not a transient. Tempted to repair legacy duplicate rows
inside `_upsert_rows`; declining - a per-write scan of the target, and
the comparator is rebuilt fresh instead. Tempted to pin `lancedb<0.26`;
declining - the code should work on the version the installer resolves.
Tempted to add a second native FTS index on `content` for literal
tokens; declining - every FTS and hybrid query would then have to name
its columns, and `fts_text` is the column the vector side already
embeds; the recall question is recorded in `docs/backlog.md`.
