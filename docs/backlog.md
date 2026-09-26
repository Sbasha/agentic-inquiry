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

## local-only-config-cleanup

Open items from [`specs/local-only-config-cleanup/spec.md`](specs/local-only-config-cleanup/spec.md).
The `.env.example` item is the deferred part of AC1; the rest are
outside the spec's boundaries.

- **`config/mcp.yaml` fails the schema:** no code loads it, yet
  `docs/mcp/configuration.md`, `docs/mcp/deployment.md` and
  `docs/mcp/security.md` say the MCP server reads it. The schema's
  `mcp.relationships`, `mcp.tokens`, `mcp.defaults`, `mcp.behavior` and
  `mcp.logging` are empty objects with `additionalProperties: false`, so
  they reject every field the `MCPConfig` dataclasses define. Decide
  whether to add those fields to the schema or retire the file and its
  docs, then add `config/mcp.yaml` to the shipped-config test if it stays.
- **Empty config section crashes `Config.load`:** a section header with
  no keys (for example `search:`) reaches `_validate_config` as `None`,
  which calls `.get` on it and raises `AttributeError` instead of
  `ConfigurationError`. Read each section with `or {}` and let the schema
  report the empty section.
- **`ai search` ignores `--project` for its event system:**
  `GraphSearchService.__init__` and `HybridSearchService.__init__` fall
  back to a bare `EventSystem()` when `SearchService` passes `None`, and
  that constructor reloads config and
  raises "project_id must be provided or set as
  storage.default_project_id" when the config leaves
  `default_project_id` unset, even with `--project demo`. The example
  config sets `default_project_id` to work around it. Pass the resolved
  project id (or the caller's event system) through.
- **`ai search` does not exit:** after printing results, the process
  stays alive until killed (reproduced with `config/default.yaml` and the
  example config, 170 s timeout). Find the non-daemon thread or executor
  left running and shut it down before returning.
- **`.env.example` still names PostgreSQL:** it carries a "PostgreSQL
  Configuration (for test-postgresql.yaml)" block. Agent permission
  settings block reading and editing the file, so remove the block by
  hand.
- **`docs/architecture/embeddings.md` describes removed embedders:** the
  page is the embeddings subsystem's only architecture doc, but most of
  it covers server-side embedding, `BedrockEmbedder` and the PostgreSQL
  adapters, so it carries the historical-reference banner. Rewrite it
  around the shipped local embedders.
- **PostgreSQL-family code leftovers:** `agentic_inquiry/storage/schemas/`
  still ships `postgresql`, `cloudsql`, `alloydb`, `rds` and `spanner`
  schemas; `BackendConfig` keeps `alloydb` handling; `NoOpEmbedder`
  documents an AlloyDB flow, and the per-backend
  `embedding_strategy: server_side` setting is still honored on shipped
  backends, where it makes indexing store zero vectors. The agent docs in
  `agentic_inquiry/storage/providers/AGENTS.md`,
  `providers/lancedb/AGENTS.md` and `providers/sqlite/AGENTS.md` still
  describe `postgresql/`, `alloydb/` and `cloudsql/` provider directories
  and a Postgres migration path, and cite a missing `docs/scaling.md`.
  Decide per item whether it serves the external provider contract in
  `storage-backends.md` or should go.
- **LanceDB ignores `database_path`:** `BackendConfig` requires
  `database_path` for a `lancedb` backend, but `LanceDBProvider` drops it
  and the connection code always uses `storage.root` +
  `storage.lancedb.path`. A user who changes it gets no error and no
  effect. Either read it or stop requiring it.
- **`ai index` ignores `embeddings.default_provider: hashing`:**
  `configure_embedder_for_backend` handles only `fastembed` and
  `local`/`local_model` and falls through to `SentenceTransformerEmbedder`
  for everything else, while `EmbeddingService._create_embedder` builds a
  `HashingEmbedder`, so index and query paths can disagree.

<!-- Add one section per spec with open work, e.g.:

## <spec-name>

- **AC<N> (deferred: <anchor>):** <what's open> — blocked on <X>; unblocked by <Y>.

-->
