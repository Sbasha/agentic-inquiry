# Spec: Recover FTS search from a stale table, and clear ruff findings

Mode: light (no risk trigger fired)

- **Status:** Implementing

## Objective

`LanceDBQueryBuilder.fts_search` retries once after a stale-table error
(another process re-created the table under a cached handle), but the retry
closure reads `safe_query`, a local of the first attempt's closure. The retry
raises `NameError: name 'safe_query' is not defined`, so a search that should
recover fails instead. Fix the retry so all four searches (vector, FTS,
hybrid, filter) share one retry path that cannot reference another attempt's
locals, and bring `ruff check agentic_inquiry tests` to zero findings.

## Acceptance Criteria

- [ ] After the table is dropped and re-created under a cached handle,
      `LanceDBManager.fts_search` returns results from the re-created table
      instead of raising `NameError`. Verified against real LanceDB on disk.
- [ ] The same recovery holds for `vector_search`, `hybrid_search` and
      `advanced_filter`.
- [ ] A non-stale error, or a stale error with no cache invalidator,
      propagates; a table gone after invalidation yields `[]`.
- [ ] `facade.py` imports `ProviderCapabilities` under `TYPE_CHECKING`.
- [ ] `uv run ruff check agentic_inquiry tests` reports zero findings.
- [ ] Each F841 and E741 finding is reviewed by hand; none is fixed by
      `--unsafe-fixes`. A dead value is deleted; a construction kept for its
      side effect stays as a bare statement.
- [ ] `mypy` reports no new errors in touched `agentic_inquiry/` files.

## Tasks

1. Red: on-disk LanceDB test re-creating the table between two searches,
   parametrized over the four search methods (FTS fails today).
2. Route the four searches through one `_search_with_stale_retry(table_name,
   table, run)` where `run` receives the table; delete the unused
   `_execute_with_retry`, whose retry reused a closure bound to the stale
   table. Sanitize the FTS query before the search function, once per call.
3. Add the `ProviderCapabilities` type-only import.
4. `ruff check --fix` for F401/F541; hand-fix F841/E741 and the
   non-auto-fixable F401 in `tests/01-agents/protocols/__init__.py`.
5. Gates: ruff, mypy on touched files, pytest baseline diff against `main`.
