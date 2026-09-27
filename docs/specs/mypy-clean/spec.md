# Spec: Clear the mypy gate on `agentic_inquiry/`

Mode: light (no risk trigger fired; type-level fixes across independent
files with no new module, dependency, or public interface)

- **Status:** Shipped (2026-09-26)

## Objective

`uv run mypy agentic_inquiry/` is a listed gate in `AGENTS.md` but reports
78 errors in 27 files on `main`, so it can't catch new type errors. Fix each
error at its cause (narrowing, correct annotations, `None` handling) so the
gate reports zero and can be enforced.

Some errors are real defects, where the code raised or returned the wrong
shape at runtime. Those get the smallest fix that makes the path do what
its surrounding code and docs say, plus a regression test. Every other fix
leaves runtime behaviour unchanged. Where the type fix would change
search, indexing, or memory behaviour, the code keeps its behaviour, the
line carries a coded `type: ignore` with a reason, and the gap goes to
`docs/backlog.md`.

## Acceptance Criteria

- [x] `uv run mypy agentic_inquiry/` reports `Success: no issues found`.
- [x] No new bare `# type: ignore`. Each new ignore names its error code
      and gives a one-line reason.
- [x] The failing-test set from `pytest -p no:randomly` on this branch is a
      subset of the failing-test set on `origin/main` run with the same
      flags (K-0001).
- [x] Each real defect has a regression test that fails on `origin/main`
      and passes on this branch:
  - `LanceDBQueryBuilder.fts_search` stale-table retry raised `NameError`
    (`safe_query` was local to the first attempt).
  - `DocumentParser.parse` on a file over `_MAX_DOC_FILE_SIZE` raised
    `TypeError` (`ParsedDocument` has no `relationships` field, and
    `doc_id`/`file_path` were missing), not the documented skip.
  - REST `/memory/store` and `/memory/recall` built `MemoryContext`
    without `conversation_id`, so store always returned `stored: false`
    and recall returned nothing. Recall's formatter also looked for a
    `.memory` attribute that `RetrievalResult` doesn't have, so once
    retrieval worked it would have returned the result's repr as content.
  - `SearchService.execute` returned raw dicts for a filter-only
    `QuerySpec` although it is typed and documented to return
    `SearchResult`s, as `LanceDBAdapter.execute` does.
  - Single-file `add_knowledge` on a backend that needs embedding polling
    passed a string as `_poll_embedding_completion`'s `poll_interval`. The
    poll raised at once, the error was logged, and `indexing.ready` fired
    before embeddings existed. It now polls with the same defaults as
    directory indexing.
- [x] `ruff check` reports no findings in the touched files.

## Boundaries

Out of scope, recorded in `docs/backlog.md` under `mypy-clean`: enabling
the initial-index relationship shortcut on the LanceDB adapter path,
branch-tagging for `ai index --branch`, the raw-text path into list-only
vector providers, and REST memory recall below the episodic threshold.

## Tasks

1. Fix annotation-only errors (inferred empty containers, reused variable
   names, missing `TYPE_CHECKING` import, `Optional` narrowing that mirrors
   an existing flag).
2. Fix the real defects, each with a regression test.
3. Align the `query_vector: list[float] | str` contract through search
   (`HybridSearchService`, `GatherContext`, the CLI's `ndarray` callers).
4. Run gates and diff the failing-test sets against `origin/main`.
