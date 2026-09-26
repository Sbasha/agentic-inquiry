# Plan: Import `agentic_inquiry.watching` without touching the filesystem

- **Spec:** [`spec.md`](spec.md)
- **Status:** Done

## Approach

Replace the import-time `_register_default_watcher()` call in
`agentic_inquiry/watching/__init__.py` with `_ensure_default_registered()`,
which `get_watcher` and `available_watchers` call on demand, following
`_ensure_default_registered` in `agentic_inquiry/cache/__init__.py`. The
built-in watcher is registered without `set_default`, so the registry's
existing rule (first registered or `set_default=True` wins) decides
precedence. A module-level lock serializes the check and the registration,
which the import lock used to do. The riskiest part is changing which
watcher `get_watcher()` returns for callers that register their own
watchers; the acceptance criteria pin each case.

## Constraints

- `WatcherRegistry` semantics stay as they are (spec Boundaries).
- `FileWatchManager.setup_file_watching` catches `ValueError` and `KeyError`
  from `get_watcher`, so construction errors that now propagate are logged
  there as "proceeding without watcher".

## Construction tests

**Integration tests:** none beyond per-task tests.
**Manual verification:** in an empty temporary directory,
`uv run --project <repo> python -c "import agentic_inquiry.watching.file_tracker"`
leaves the directory empty.

## Tasks

### T1: Importing the package creates no files

**Depends on:** none

**Tests:**
- `test_watching_import_creates_no_files` (red before T2).

**Approach:**
- Add the subprocess test using the file's existing `_run` helper.

**Done when:** the test fails on `main` because `.agentic-inquiry` appears in
the scratch working directory.

### T2: Default watcher resolves lazily with caller precedence

**Depends on:** T1

**Tests:**
- `test_watching_import_creates_no_files` green.
- `test_watching_built_in_default_is_a_file_watcher`.
- `test_watching_default_watcher_registers_on_first_lookup`, parametrized
  over `get_watcher()`, `get_watcher('default')` and `available_watchers()`
  as the first call, including the rebuild after `unregister_watcher`; a stub
  replaces `FileWatcher` so each case skips the real build.
- `test_watching_caller_watchers_skip_the_built_in_default`.
- `test_watching_default_watcher_errors_reach_the_caller`.
- `test_watching_concurrent_first_lookups_build_one_default`.

**Approach:**
- Remove `_register_default_watcher()` and its import-time call; import
  `FileWatcher` at module top.
- Add `_ensure_default_registered()` under a `threading.Lock`.
- In `get_watcher`, fall back to the `"default"` name when no default is set,
  and ensure the built-in only for `"default"`.

**Done when:** all T2 tests, `tests/watching/` and the `tests/indexing/`
watcher tests pass; ruff and mypy are clean on the touched files.

## Rollout

Ships in one PR. Reverting the PR restores import-time registration.

## Risks

- A caller that registered its own watcher without `set_default` and relied
  on `get_watcher()` returning the built-in now gets its own watcher. No
  caller in the repository does this.
