# Spec: Main test suite green

Mode: full (the config JSON schema is a published configuration contract, the
memory-layer fix changes concurrency behaviour in shipped code, and the cohere
reranker is removed).

- **Status:** Shipped (2026-09-26)
- **Owner:** sammybasha
- **Plan:** [`plan.md`](plan.md)
- **Constrained by:** [`docs/CHARTER.md`](../../CHARTER.md) principle 1 (local only)
- **Contract:** `config/config.schema.json` (the user-facing configuration schema)

## Objective

`INQUIRY_EMBEDDING_DEVICE=cpu uv run pytest tests` passes deterministically.
Every failure is fixed at its root cause: product code is corrected where it is
wrong, a test is rewritten where its fixture drifted from the current contract,
and a test is deleted only where it pins behaviour the product no longer has.

## Boundaries

### Always do

- Reproduce each failure group before changing anything.
- Prefer real collaborators (a temporary LanceDB directory, a loaded `Config`,
  real `SearchResult` and `RetrievalResult` objects) over `MagicMock` stand-ins
  when a fixture has drifted from the object it imitates.
- Say in the commit which deleted tests pinned removed behaviour.

### Ask first

- Removing a product feature or config key to make a test pass.

### Never do

- Add a dependency, module or storage table layout beyond the declared
  `mcp_sessions` schema.
- Edit an assertion only so it passes against wrong product behaviour.
- Mark a test `skip`/`xfail` to hide a failure.

## Testing Strategy

The whole suite is the acceptance test. Before/after failing sets come from
`--junitxml` reports diffed as sets, both runs with identical flags. Each
product fix has a regression test at the lowest level that shows the defect,
confirmed red against the unfixed code. The memory race is checked by
repeating the lifecycle test enough times that the pre-fix failure rate (about
one run in four) would show.

## Acceptance Criteria

Configuration and storage:

- [x] `Config.load().to_dict()` written to YAML loads back through
      `Config.load(path)`; the schema describes every `mcp.relationships`,
      `mcp.tokens`, `mcp.defaults`, `mcp.behavior` and `mcp.logging` key the
      dataclasses define.
- [x] The `mcp_sessions` table has a declared schema, so a first session without
      a description or log file does not block later sessions that have one; a
      table left null-typed by an older release fails with an error naming the
      columns and the fix.
- [x] `LanceDBSessionStorage.list_sessions` and `find_expired_sessions` see
      sessions of every project, not only the storage facade's project.
- [x] `StorageFacade.advanced_filter` accepts a Filter AST for chunk and
      relationship tables on LanceDB, as it documents; `RelationshipResolver`
      filters relationships on the schema column `type`.

Sessions and MCP tools:

- [x] `SessionManager` statistics count files and languages of an indexed
      project and report `last_indexed` from the chunks' `indexed_at`.
- [x] `validate_session` returns False for a session expired in the cache, even
      when the database copy is still active.
- [x] `RateLimiter.get_session_stats` returns the same keys for an unknown
      session as for a tracked one.
- [x] `get_project_info` reports 0 counts, a warning and no "not yet indexed"
      guidance, never -1, when the index statistics cannot be read.
- [x] Architectural pattern discovery returns at most `limit` patterns.
- [x] The ripgrep fallback matches the query as literal, case-insensitive text,
      like the Python fallback, including queries that start with `-`.
- [x] `discover_branches` never reports the remote's `HEAD` symref as a branch,
      on git versions that shorten `refs/remotes/origin/HEAD` to `origin`.

Memory and embeddings:

- [x] Concurrent access-stat refreshes and importance updates on an episodic or
      semantic memory item leave exactly one row carrying the latest importance,
      and a deleted item is not re-created by a pending refresh or a racing
      `update_importance`.
- [x] A refresh whose write fails leaves the previous version of the item
      readable, and repeated retrieves count every access.
- [x] Negate and supersede persist the new status on the episodic and semantic
      tiers.
- [x] Embedders created and loaded concurrently in one process all load and
      embed; no load leaves the process unable to load models.

Reranking:

- [x] `cohere` is not a valid `reranker_type`: the hosted Cohere API reranker is
      removed from the schema enum, `VALID_RERANKER_TYPES`, the reranker package
      and the docs.

Tests:

- [x] The parser-examples test module is deleted: `examples/parsers/` never
      existed in this repository and no document ships it.
- [x] The `ParserChunk` metadata tests pin the current contract (list and dict
      values accepted); the rejection and error-message tests are deleted, and
      AGENTS.md, `docs/development/parser-guidelines.md` and
      `docs/customization/extending.md` describe the JSON-serialized contract.
- [x] Session, persistence, retrieval-engine, config-persistence, enterprise,
      overlay, factory, memory-system, gatherer, build-context, context-builder,
      provider, pattern-analyzer, keyword, server-initialization, index-state,
      maintenance, marker and parser-pipeline tests use fixtures that match the
      current APIs.
- [x] Every wall-clock budget test is marked `perf` and runs only with
      `INQUIRY_PERF_TESTS=1`; property tests run with no Hypothesis deadline.
- [x] The full suite has zero failures with
      `INQUIRY_EMBEDDING_DEVICE=cpu uv run pytest tests`.

## Assumptions

- pytest-randomly is not a project dependency, so the lifecycle-test flake is a
  timing race, not an ordering dependency (verified: 3 of 12 isolated runs
  failed before the fix).
- The memory-layer lock serialises writers within one process. Two processes
  writing the same memory table can still interleave.
