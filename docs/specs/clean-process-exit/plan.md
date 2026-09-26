# Plan: Clean process exit

- **Spec:** [`spec.md`](spec.md)
- **Status:** Executing

## Approach

Fix each owner that opens an aiosqlite-backed store without closing it,
then replace the test harness's silent `os._exit` with a watchdog that
acts only when interpreter shutdown actually stalls.

A full-suite census (a throwaway plugin recording where each surviving
non-daemon thread was started) finds 102 leaked `aiosqlite` connection
threads and 16 idle pool workers. The pool workers do not block exit.
The connections come from four owners: `create_mcp_services` callers
without a complete teardown (MCP server shutdown and MCP test fixtures),
the `ai memory` commands, `reconcile._open_runtime`, and tests that
create an `EventStore` directly. Outside pytest, the same leaks make
`ai memory save` and `ai mcp` over stdio hang after finishing their work.
The census also finds tests that ignore their `tmp_path` and write
`events.db`, `file_tracker.db`, `lancedb/` and `logs/` under the cwd's
`./.agentic-inquiry`; that is why the old hook compacted that directory.

The riskiest part is MCP server shutdown, which gains
`MemorySystem.shutdown()` (final consolidation) and `StorageFacade.close()`.

## Constraints

- AGENTS.md: async-only I/O, lazy logging, complete type annotations.
- The storage provider contract stays unchanged; `StorageFacade.close()`
  is already public and idempotent.

## Construction tests

**Integration tests:** full-suite census run (throwaway plugin, not
committed) shows no surviving `aiosqlite` thread and no writes under the
cwd's `./.agentic-inquiry`; failing-test set diffed against the
pre-change baseline with identical flags.

**Manual verification:** the user's repro command prints its summary.

## Design (LLD)

### Design decisions

- `close_mcp_services(services)` lives beside `create_mcp_services`: the
  constructor's module owns the destructor. The failure path, the server
  shutdown and the MCP fixtures all call it. Rejected: per-fixture
  teardown copies (four already diverged), and daemon threads (aiosqlite
  owns the thread class). Traces to: ACs `close_mcp_services`, `ai mcp`.
- The watchdog lives in `tests/helpers/thread_watchdog.py`, a pytest
  plugin loaded by `tests/conftest.py` through `pytest_plugins`, so a
  subprocess test can load it alone. `pytest_sessionstart` keeps the
  session; `pytest_unconfigure` registers a callback with
  `threading._register_atexit`. That callback runs when
  `threading._shutdown` begins, before `concurrent.futures` joins its
  workers and before non-daemon threads are joined, and starts a daemon
  timer. If a non-daemon thread other than the main thread is still alive
  10 seconds later, the timer flushes stdout, writes the report to stderr,
  flushes it, and calls `os._exit` with `session.exitstatus`, or 1 when
  that is 0 or no session was recorded. With no such thread it returns and
  finalization (atexit handlers, coverage save) proceeds.
  A process that shuts down cleanly ends before the timer fires. A host
  that calls `pytest.main()` and keeps running is unaffected until its own
  shutdown. Rejected: a timer started at `pytest_unconfigure` (fires on
  hosts that keep running and on slow-but-finite shutdowns it did not
  measure); an eager check at unconfigure (misreports idle pool workers);
  `faulthandler.dump_traceback_later(exit=True)` (always exits 1 and
  prints no thread names). Traces to: AC leak report.
- A leak fails an otherwise green run: a silent leak is how 118 threads
  accumulated behind the old `os._exit`.

### Failure, edge cases & resilience

- `close_mcp_services` receives a partial mapping on the failure path;
  absent keys are skipped. A raising closer is logged at warning with
  `exc_info` and the next one still runs.
- `create_memory_system` and `_open_runtime` close the storage they opened
  when a later step raises, then re-raise.
- `ai mcp` over stdio creates services in one `asyncio.run` and shuts them
  down in another; aiosqlite and `StorageFacade.close()` tolerate that.
  The subprocess test in T2 is the check.

## Tasks

### T1: Test-owned stores close and stay under `tmp_path`

**Depends on:** none
**Mode:** goal-based (census)
**Touches:** tests/database/test_factories.py, tests/events/test_system.py, tests/events/test_performance.py, tests/utils/test_logging_path_resolution.py, tests/conftest.py, tests/memory/test_memory_system.py

**Tests:**
- Census over the touched files shows no surviving `aiosqlite` thread.
- The touched files run from an empty cwd leave no `./.agentic-inquiry`
  contents.

**Approach:**
- `event_stores` fixture in `test_factories.py` closes each store created.
- The shared `mock_config` fixture roots storage at `tmp_path` and clears
  explicit `storage.backends`, so a developer's `ai setup` config cannot
  point it at a real store; it asserts the LanceDB, event-store and
  file-tracker paths resolve under `tmp_path`. This also covers
  `tests/mcp/test_context_builder_registration.py`, the census's other
  cwd writer.
- `test_stop_flushes_pending_events` closes the read-back store.
- Performance tests set `config.storage.root` to `tmp_path`; the
  logging-path tests, which assert the default relative root, run with
  `monkeypatch.chdir(tmp_path)`.
- The files in the first AC need two pre-existing breaks fixed to run:
  `integration_config` passes the parser config subclasses
  `ParsersConfig` declares, and `test_memory_system.py` imports memory
  layers from `agentic_inquiry.memory.layers`.

**Done when:** both tests above hold and the touched files pass.

### T2: `close_mcp_services` releases MCP services

**Depends on:** none
**Mode:** TDD, plus goal-based subprocess check
**Touches:** agentic_inquiry/mcp/factories.py, agentic_inquiry/mcp/server.py, tests/mcp/test_factories.py, tests/mcp/test_analyze_impact_integration.py, tests/mcp/test_comprehensive_agent_validation.py, tests/mcp/test_entity_operations_after_schema_changes.py, tests/mcp/test_understand_entity_integration.py, tests/mcp/test_context_builder_registration.py, tests/mcp/test_build_context_integration.py, tests/events/test_integration.py, tests/mcp/test_mcp_stdio_exit.py

**Tests:**
- Order: maintenance task cancelled and awaited, then
  `memory_system.shutdown`, `event_system.stop`, `storage.close`.
- Partial mapping `{"storage": s}` closes only `s`.
- `memory_system.shutdown` raising still leads to `event_system.stop` and
  `storage.close`.
- Integration: `create_mcp_services` with the hashing embedder and
  `tmp_path` storage, then `close_mcp_services`, leaves the set of live
  `aiosqlite.core.Connection` threads as it was before the call.
- Integration: `create_mcp_services` with `MemorySystem.initialize`
  patched to raise leaves the aiosqlite thread set unchanged and no
  pending maintenance task.
- Subprocess: `python -m agentic_inquiry.cli mcp --project-id demo` with
  the hashing embedder in a temp git project logs `MCP server ready`;
  after stdin closes it exits 0 within 30 seconds.
- Existing `test_shutdown_cancels_maintenance_task` and
  `test_shutdown_cleans_up_services` stay green.

**Approach:**
- Extract the body of `cleanup_on_failure` into `close_mcp_services`;
  the failure path calls it with what it built.
- `MCPServer.shutdown()` calls it in place of its own maintenance-task
  and event-system blocks; drop the no-op `db_manager` block.
- Every test that calls `create_mcp_services` for real tears down through
  it.

**Done when:** the new tests and `tests/mcp/` pass.

### T3: `ai memory` commands close their storage

**Depends on:** none
**Mode:** goal-based subprocess check, plus TDD for the failure path
**Touches:** agentic_inquiry/cli/memory.py, tests/cli/test_memory_exit_code.py

**Tests:**
- Subprocess `save`, then `list`, then `recall` with the hashing embedder
  in a temp git project each exit 0 within 60 seconds (red before: `save`
  times out).
- `create_memory_system` with `MemorySystem.initialize` raising closes the
  storage it opened and re-raises.

**Approach:** `save_command`, `recall_command` and `list_command` close
the storage in a `finally`; `create_memory_system` closes it on its own
failure.

**Done when:** both tests pass and the manual `ai memory save` repro
exits.

### T4: Reconcile releases its runtime

**Depends on:** T3
**Mode:** TDD
**Touches:** agentic_inquiry/integration/reconcile.py, agentic_inquiry/memory/system.py, tests/memory/test_memory_system.py, tests/integration/test_integration_maintenance_tick.py

**Tests:**
- An initialized `MemorySystem` with an active context:
  `shutdown(consolidate=False)` leaves the consolidation and
  context-manager tasks done and never calls
  `consolidation_engine.consolidate`.
- On a real queued capture (the maintenance-tick fixture), a tick that
  commits calls `MemorySystem.shutdown(consolidate=False)` once and leaves
  no new aiosqlite thread.
- A pass whose `_commit_one` raises does the same and re-raises.
- A pass whose `IndexingPipeline` constructor raises inside
  `_open_runtime` leaves no new aiosqlite thread and re-raises.

**Approach:** `MemorySystem.shutdown` gains `consolidate: bool = True`.
In `_reconcile_locked`'s `finally`, when the runtime was opened, await
`memory.shutdown(consolidate=False)` then `storage.close()`, each failure
logged; `_open_runtime` closes storage on its own failure.

**Done when:** the three tests pass and the maintenance-tick integration
test is green.

### T5: Harness exits after its summary; watchdog reports leaks

**Depends on:** T1-T4
**Mode:** goal-based subprocess test, plus manual QA
**Touches:** tests/conftest.py, tests/helpers/thread_watchdog.py, tests/test_thread_watchdog.py

**Tests:**
- Subprocess `python -m pytest -p tests.helpers.thread_watchdog` with
  `PYTHONPATH=<repo root>`, cwd and `--rootdir` set to `tmp_path` (so the
  repo's ini does not apply), on a generated test that starts a
  non-daemon thread waiting forever: stdout has `1 passed`, stderr names
  the thread, exit status 1.
- Same with a test that leaks nothing: exit status 0, no report, and the
  run ends well before the grace period.
- Manual: the user's repro prints its summary.

**Approach:** delete `pytest_sessionfinish`'s compaction, private executor
surgery and `os._exit`; add the watchdog plugin; register it from
`tests/conftest.py`.

**Done when:** both subprocess tests pass and the manual check is
observed and recorded in the PR.

## Rollout

Ships as one PR. No migration, no config. Rollback is a revert.

## Risks

- MCP server shutdown takes longer by the final memory consolidation. If
  the client kills the server during it, the event flush and storage
  close that follow are lost.
- A slow-but-finite thread that needs more than 10 seconds at interpreter
  shutdown is reported as a leak and fails the run.

## Changelog

- 2026-09-26: initial plan
