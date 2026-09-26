# Spec: Clean process exit

- **Status:** Implementing
- **Owner:** Sbasha
- **Plan:** [`plan.md`](plan.md)
- **Constrained by:** none
- **Contract:** none

Mode: full (adds `close_mcp_services`, a public teardown paired with
`create_mcp_services`, and changes MCP server shutdown).

## Objective

The test suite, the `ai memory` commands, the MCP server and the
integration reconcile close every store they open that owns a non-daemon
thread, so each process ends when its work ends. `ai memory save`,
`ai memory list` and `ai memory recall` print their result and exit.
`ai mcp` over stdio exits after its client closes stdin. A reconcile pass
releases the runtime it opened. A pytest run prints its full terminal
summary, writes its junitxml, and exits with pytest's own status without
the test harness cutting it short. If a test still leaks a thread that
blocks interpreter exit, the run names that thread and its stack and
fails, instead of hanging or exiting silently. The test harness never
reads, compacts or prunes the developer's real `./.agentic-inquiry`
store. Leaks in other CLI commands and in `ai server` are tracked in
[`docs/backlog.md`](../../backlog.md#clean-process-exit).

## Boundaries

### Always do

- Close a resource in the scope that opened it (`finally`, fixture
  teardown, or the opener's own failure path), in dependents-first
  order: maintenance task, memory system, event system, storage.
- Keep teardown failures logged and non-fatal so one failing service does
  not keep the others open.
- Point tests that already receive `tmp_path` at it for every store they
  create.

### Ask first

- Changing `EventStore`, `SQLiteEventStorage`, `EventSystem` or
  `StorageFacade` lifecycle semantics, including their close-on-error
  behavior.
- Changing the `os._exit` calls in `agentic_inquiry/cli/integration.py`
  and `agentic_inquiry/cli/status.py`.

### Never do

- No new dependency or top-level directory.
- No `os._exit` from the test harness before interpreter shutdown has
  begun, which is after pytest has written its summary and reports.
- No mutation of `concurrent.futures` private state from tests.
- No test-session hook that opens a store under the process cwd.

## Testing Strategy

- `close_mcp_services` ordering, partial-mapping and error isolation:
  TDD, unit tests with async mocks, because the invariant (every present
  service closed once, in order, despite a failing peer) is compressible.
  One integration test with real `tmp_path` storage checks that no
  aiosqlite thread survives `create_mcp_services` then
  `close_mcp_services`.
- Reconcile and `create_memory_system` release what they opened: TDD,
  unit tests replacing the runtime pieces with async mocks, covering the
  committed, raising and partially-built cases.
- `ai memory save|list|recall` and `ai mcp` exit: goal-based, end-to-end
  subprocess tests with a timeout, because the defect only shows as a
  process that never exits.
- Leak report: goal-based, a subprocess test runs pytest with the
  watchdog plugin on a generated test that leaks a non-daemon thread.
- Clean pytest exit on real runs: manual QA, observed output of the
  user's repro command and the full suite.
- No leaked threads and no cwd writes suite-wide: goal-based, a full-suite
  run with a throwaway census plugin.

## Acceptance Criteria

- [ ] `INQUIRY_EMBEDDING_DEVICE=cpu uv run pytest tests/database/test_factories.py tests/memory/test_memory_system.py`
      prints its `=== ... in Ns ===` summary line.
- [ ] `uv run pytest` over the full suite prints its summary line and
      exits with pytest's status.
- [ ] At the end of a full-suite run no `aiosqlite` connection thread is
      alive.
- [ ] When a test leaks a thread that blocks interpreter exit, the run
      prints pytest's summary, then, if a non-daemon thread is still alive
      10 seconds after interpreter shutdown starts, writes each such
      thread's name, type and stack to stderr and exits with pytest's
      status, or 1 when that status was 0 or no session was recorded. When
      no non-daemon thread remains, the watchdog does nothing and
      finalization completes normally.
- [ ] `tests/conftest.py` neither opens nor compacts
      `./.agentic-inquiry/lancedb` and does not touch `concurrent.futures`
      private state.
- [ ] With `INQUIRY_EMBEDDINGS_DEFAULT_PROVIDER=hashing` in a fresh git
      project, `ai memory save "<text>" --importance 0.9`, then
      `ai memory list` and `ai memory recall "<text>"`, each exit 0
      within 60 seconds.
- [ ] With the hashing embedder, `ai mcp --project-id demo` over stdio
      logs `MCP server ready`, then exits 0 within 30 seconds of its stdin
      closing.
- [ ] After `create_mcp_services` then `close_mcp_services`, and after a
      `create_mcp_services` call that fails partway, no aiosqlite thread
      from those services is alive and the maintenance task is done.
- [ ] After a reconcile pass that opened its runtime, whether the pass
      commits, fails or raises, the memory system's background tasks are
      stopped without a final consolidation and the storage is closed.
- [ ] When `create_memory_system` fails after opening storage, the
      storage is closed before the error propagates.
- [ ] A full-suite run changes nothing under the cwd's `./.agentic-inquiry`
      except creating that directory empty on import (backlog: importing
      `agentic_inquiry.watching`).

## Assumptions

- Technical: aiosqlite 0.21 runs each connection on a non-daemon
  `threading.Thread` blocked on a queue until `close()` (source:
  `.venv/.../aiosqlite/core.py:97`, census of surviving threads).
- Technical: idle `ThreadPoolExecutor` workers do not block exit;
  `concurrent.futures` joins them from a `threading._register_atexit`
  hook (source: CPython 3.12 `concurrent/futures/thread.py`).
- Technical: `threading._register_atexit` callbacks run at the start of
  `threading._shutdown`, before non-daemon threads are joined, and daemon
  threads keep running while the main thread waits there (source: CPython
  3.12 `Lib/threading.py`, `Py_FinalizeEx`).
- Technical: `StorageFacade.close()` closes the events provider's SQLite
  writer connection (source: `agentic_inquiry/storage/facade.py:445`).
- Technical: aiosqlite creates each call's future on the calling loop, so
  closing a connection on a different event loop than the one that opened
  it works; `ai mcp` over stdio does that (source:
  `agentic_inquiry/mcp/cli.py:369-388`, `aiosqlite/core.py`).
- Product: MCP server shutdown runs `MemorySystem.shutdown()`, which
  performs a final consolidation that persists working memories, before
  the event system and storage close. This is the teardown the failure
  path of `create_mcp_services` already runs (source:
  `agentic_inquiry/mcp/factories.py:145`); it lengthens shutdown by that
  consolidation.
- Product: a reconcile pass stops its memory system without the final
  consolidation, so rows it committed are left as committed and the
  project lock is not held for a consolidation (source:
  `agentic_inquiry/integration/reconcile.py:62-70`,
  `agentic_inquiry/memory/system.py:381-395`).
- Technical: `ai mcp` over stdio builds its services inside one
  `asyncio.run` that cancels their background tasks on return, so
  maintenance ticks run only on the http and sse transports (source:
  `agentic_inquiry/mcp/cli.py:369-388`; backlog item).
- Process: specs follow `docs/CONVENTIONS.md` § 4 (source:
  `docs/specs/pin-python-upper-bound/spec.md` for shape).
