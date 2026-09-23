# Plan: AFP lifecycle contract

- **Spec:** [`spec.md`](spec.md)
- **Status:** Drafting

> **Plan contract:** this is the implementation strategy. Unlike the spec, this
> document is allowed to change as you learn. When it changes substantially
> (a different approach, not just a re-ordering), note why in the changelog
> at the bottom.

## Approach

Add one package, `agentic_inquiry/integration/`, that owns the contract end to end: `contract.py` (constants, request parsing, response builders, byte budget, rendering), `state.py` (the SQLite ledger, bindings, the project identity and marker files), `capabilities.py`, `hooks.py` (the per-event orchestrator) and `reconcile.py` (commits queued work using the existing memory system and indexing pipeline). The CLI dispatcher gains early branches for `--version`, `capabilities`, `integration`, `mcp` and `status` that run before any heavy import, and `agentic_inquiry/__init__.py` loses its import-time side effects. Contract shapes live as JSON Schema under `contracts/jsonschema/` and the black-box contract tests validate every response against them.

Order of operations: governance documents first, then import hygiene and the quiet dispatcher, then the pure contract module, then the ledger, then the verbs in dependency order (capabilities; enable, disable, status, purge; hook; recall; reconcile; mcp and status), then the loopback fix, the documentation pass and the recorded journey. The riskiest part is keeping the hook path free of the runtime's import graph while still reading LanceDB inside SessionStart; the deadline guard and the import-hygiene tests are the defence.

## Constraints

- RFC-0002 defines the surface and the charter amendment; ADR-0004 fixes the lineage; ADR-0005 fixes the hot-path budget, the durable authority and the queued-then-reconciled model.
- ADR-0001 and ADR-0002: storage access goes through `StorageFacade` and the provider protocols; the ledger is a new SQLite file the facade does not own, by design.
- `AGENTS.md`: async at the I/O boundary, with the one stated exception of the synchronous ledger module reached through `asyncio.to_thread` (recorded in the charter by T12); validate at boundaries; complete type annotations; lazy logging; no new dependency without an ADR (none is added).
- `CHANGELOG.md` is never hand-edited (the owner's standing rule), although `docs/CONVENTIONS.md` asks for a note on user-visible changes; the conflict is recorded in `docs/backlog.md` for the owner to settle, and this change leaves the file untouched.
- The AFP pack hook is the acceptance oracle: its statuses, receipt kinds, budget invariant and exit-code rule are fixed.
- The binding under `INQUIRY_HOME` is the only authority for enablement; the marker is a hint. Confinement reuses `validate_file_path`; the storage namespace reuses `validate_project_id`; prompt text reaches the store only through `StorageFacade.fts_search`. Recall filters use the dict form `LanceDBMemoryAdapter.query` accepts, which reaches the blessed translator; the Filter AST is preferred wherever an adapter accepts it.
- Every hook response validates against the response schema, is bounded by `bound_response`, contains no absolute path, and its status comes from `finalize(response, refusal)` with the refusal as an explicit input. Every regular expression in the contract is applied with `re.fullmatch`; the runtime writes its own error messages and never copies validator exception text.

## Construction tests

**Integration tests:** `tests/integration/test_afp_lifecycle_contract.py` implements AC1, AC2, AC4 to AC21 and AC23 to AC28 as black-box subprocess tests (AC22's worst case is a unit test) with a shared fixture (`tmp_home` for `INQUIRY_HOME`, `tmp_project` as a git repository onboarded through `LocalSetup`, hashing embedder with 128 dimensions); `tests/unit/test_import_hygiene.py` implements AC3; `tests/cli/test_dispatch.py` implements AC1's legacy route and AC29's dispatch; `tests/integration/test_integration_maintenance_tick.py` implements AC29's ledger transition.
**Manual verification:** AC32, owned by T13.

## Design (LLD)

### Design decisions

- One package, one public function per verb (`capabilities()`, `hook()`, `enable()`, `disable()`, `status()`, `reconcile()`, `purge()`); `cli/integration.py` only parses arguments and prints. Traces to AC2, AC4 to AC29.
- Project identity (16 hex, ledger path, bindings) and storage namespace (`storage.default_project_id`, LanceDB rows, `ai mcp`) are two recorded values with two jobs. Traces to AC10, AC13, AC17, AC29.
- The ledger, not LanceDB, is the durable authority for captures; LanceDB rows are a projection committed by reconcile. Traces to AC14, AC16, AC17.
- The binding is the only authority for enablement, owner, policy and the bound root; the marker is an adapter hint. Traces to AC6, AC12, AC13.
- Ledger key: SHA-256 of `json.dumps([owner, client, project_identity, session_id, event, event_id], separators=(",", ":"), ensure_ascii=True)`. Traces to AC14.
- Status precedence is computed once, in `contract.finalize(response, refusal)`: unsupported, error (the explicit refusal), inert, then partial if any receipt's row is not `committed`, any row is `pending`, `committing` or `failed`, or a deadline skip, else ok; `durable_store_absent` and `budget_exhausted` are advisory and never raise the status. Traces to AC5, AC16, AC23.
- Hooks never load the model or start a process; commitment happens in `reconcile` and in the MCP server's maintenance tick. Traces to AC6, AC26, AC29.
- Client support is a table in `contract.py`; the same six events for the three clients. Traces to AC2, AC7.

### Data & schema

`INQUIRY_HOME/projects/<project_identity>/records.sqlite3`, `PRAGMA user_version = 1`, WAL, `synchronous=NORMAL`, `busy_timeout` 10000 for operator verbs and `min(remaining deadline, 10 s)` inside a hook (a timeout yields `ledger_unavailable`, AC23):

- `integration_config(project_id TEXT, client TEXT, owner TEXT, enabled INTEGER, project_root TEXT, config_path TEXT, storage_project_id TEXT, policy TEXT, updated_at TEXT, PRIMARY KEY(project_id, client))`
- `integration_events(key TEXT PRIMARY KEY, project_id, client, owner, session_id, event, event_id, kind TEXT CHECK(kind IN ('capture','refresh')), payload TEXT, input_hash TEXT, state TEXT CHECK(state IN ('pending','committing','committed','failed','purged')), attempts INTEGER, deliveries INTEGER, lease_until TEXT, resets INTEGER NOT NULL DEFAULT 0, last_reset_at TEXT, receipt TEXT, result TEXT, created_at TEXT, updated_at TEXT)` with index `(project_id, client, state, created_at)`; `payload` holds only what the two consumers need, the observations for a capture row and the confinement-resolved project-relative artifact paths for a refresh row, never `query`; a `purged` row (NULL `payload`, `input_hash` and `event_id`, AC27 step zero) is terminal: recall, reconcile and the pending counts skip it; `lease_until` is the claim lease of AC17 (40 s); `integration_tombstones(key TEXT PRIMARY KEY, kind TEXT NOT NULL, erased_at TEXT)` keeps the keys step three deleted (with their kind, so `event_purged` names the original `durable_id`) for 48 hours, swept by every writing operator verb, so AC14 answers `event_purged` after a completed purge
- `integration_notified(project_id, client, session_id, code, first_at, PRIMARY KEY(project_id, client, session_id, code))`
- `project_id` matches `^[0-9a-f]{16}$` before any path or query use; `records_path` refuses anything else. `project.toml` grammar, written and read by the runtime only: `[project]`, `id = "<16 hex>"`, `schema = 1`, nothing else, at most 4096 bytes.

Project files: `<project_root>/.agentic-inquiry/project.toml` (committed) and `<project_root>/.agentic-inquiry/integration.json` (`{"schema_version": 1, "project_id": ..., "clients": {"<client>": {"owner": ..., "enabled": bool}}}`, gitignored). Traces to AC10 to AC13.

### Interfaces & contracts

`contracts/jsonschema/afp-lifecycle-hook-request.schema.json`, `afp-lifecycle-hook-response.schema.json`, `afp-lifecycle-capabilities.schema.json`; `x-spec: docs/specs/afp-lifecycle-contract/spec.md`. The CLI grammar and both code sets are in `docs/guides/reference/lifecycle-cli.md`. Traces to AC2, AC4, AC8, AC28.

### State & control flow

`hook()` gate order: client and event (unsupported) → stdin read capped at 1048577 bytes, parse, admitted keys, `owner` value, canonical `project_root`, `session_id` (error) → project identity from `project.toml` (error) → binding for `(identity, client)`: no database and no marker claiming this client is plain inert; no database with a marker claiming this client is inert plus `durable_store_absent` on SessionStart only; a row that is absent or disabled is inert; a stored root that differs from the request root, or an empty or invalid stored namespace, is `project_identity_invalid` → owner conflict against the binding (error) → bounds including `metadata`, artifact confinement through `validate_file_path`, then the exclusion floor, the policy's ignore-pattern snapshot, the binary sniff and the size cap (advisory `artifact_ignored`), then event identity (error, or read-only allowed) → policy read fail-closed (`capture_disabled`, `refresh_disabled`, recall off) → ledger `new | duplicate | conflict` → event handler → pending listing → `bound_response()` (AC22 post-condition) → `finalize()` (AC5) → exit code. SessionStart and UserPromptSubmit add the deadline-guarded read stage after the ledger step unless `recall` is false. A top-level handler turns any escaped exception into `internal_error` with empty stderr. Traces to AC4 to AC9, AC12 to AC16, AC23 to AC25.

### Failure, edge cases & resilience

Every refusal is a protocol response with the complete shape. The bridge may kill the process at its deadline: ledger writes happen in one transaction before the response, so a killed process leaves either nothing or a complete row, and the next delivery reads it as a duplicate. `reconcile` marks `failed` with `attempts`, retries below 3 attempts and never deletes a row; a commit is two-phase (`committing` with recorded ids, then `committed`) and idempotent through the recorded ids and an exact `task_id` lookup; `purge` is the only deletion. `notify` is recorded per `(identity, client, session_id, code)` so a message fires once per session; pre-binding refusals notify every time because no ledger is available. Traces to AC14, AC17, AC24, AC27.

### Quality attributes (NFRs)

Latency budgets in AC2, AC3, AC6, AC26 are enforced by subprocess tests with warm-run thresholds; heavy modules are asserted absent from `sys.modules`; the response size bound in AC22 is a unit test over the worst case. Traces to AC1 to AC3, AC22, AC26.

### Dependencies & integration

Reused: `agentic_inquiry.cli.env_resolver.resolve_environment` and `load_config_for_environment`, `agentic_inquiry.mcp.utils.validation.validate_file_path` and `PathValidationError`, `StorageFacade.from_config`, `fts_search`, `count_chunks`, `count_entities`, `count_relationships`, `LanceDBMemoryAdapter.query`, `MemorySystem.store` and `create_agent_context`, `IndexingPipeline.reindex_document`, `remove_file_data`, `flush_pending_relationships`, the parser chain and file tracker, `embeddings.factory.configure_embedder_for_backend`, `agentic_inquiry.cli.memory.create_memory_system` (made public in place), `agentic_inquiry.mcp.cli.main`, the maintenance loop body at `agentic_inquiry/mcp/factories.py:337-351` (a closure inside `create_mcp_services`, extracted by T10). Reused seam: the base's own indexing update path (`ParserChain.parse(path)`, `reindex_document`, `remove_file_data`) with absolute canonical paths, so no parser API changes and `document.py`'s single-worker executor keeps guarding the document parsers. Reused seam: `ConnectionManager(connection_factory=...)`, a zero-argument callable that already exists (`agentic_inquiry/database/connection.py:62`, forwarded by `LanceDBManager`), so reconcile opens its store with `read_consistency_interval=timedelta(0)` without changing the class; `pyproject.toml` pins `lancedb>=0.8.0,<0.26`. New dependency: none.

## Tasks

### T0: Governance documents exist and every index row resolves (AC31, index rows)

**Depends on:** none
**Mode:** goal-based

**Tests:**
- `python3 .claude/skills/work-loop/scripts/lint-spec-status.py && grep -q 0002-afp-lifecycle-contract docs/rfc/README.md && grep -q 0004-agent-vault docs/adr/README.md && grep -q 0005-afp-lifecycle docs/adr/README.md && grep -q 0005-afp-lifecycle docs/README.md && grep -q 0004-agent-vault docs/README.md && grep -q afp-lifecycle-contract docs/specs/README.md && test -f contracts/jsonschema/afp-lifecycle-hook-request.schema.json && test -f contracts/jsonschema/afp-lifecycle-hook-response.schema.json && test -f contracts/jsonschema/afp-lifecycle-capabilities.schema.json` exits 0.

**Approach:**
- RFC-0002 (Accepted by the approver in session), ADR-0004 (Accepted), ADR-0005 (Proposed until T12), this spec and plan; index rows in `docs/rfc/README.md`, `docs/adr/README.md`, `docs/README.md`, `docs/specs/README.md`; the three schemas under `contracts/jsonschema/`.

**Done when:** the command exits 0.

### T1: Importing `agentic_inquiry` is side-effect free (AC3)

**Depends on:** none
**Mode:** TDD (subprocess tests)

**Tests:**
- `tests/unit/test_import_hygiene.py`: no heavy module after import; no file or directory created in the cwd or under `INQUIRY_HOME`; `agentic_inquiry.search`, `agentic_inquiry.storage` and `agentic_inquiry.memory` resolve through `__getattr__` while an unknown name raises `AttributeError`; `__all__` unchanged; the import itself under 0.1 s warm, timed inside the child.
- Existing `tests/integration/test_logging_integration.py`, `tests/utils/test_logging_path_resolution.py` and `tests/unit/test_logging_config.py` stay green.

**Approach:**
- `agentic_inquiry/__init__.py`: remove `LoggingConfigurator.setup()` and the eager `from . import ...`; keep `__all__`; PEP 562 `__getattr__` that imports `agentic_inquiry.<name>` for any subpackage and raises `AttributeError` otherwise.
- `cli/__main__.py`: call `LoggingConfigurator.setup()` only from the interactive branches (index, search, entity, memory, patterns, lineage, services, validate, agent-test, onboard, shell, server, serve, the legacy flag route, the no-argument client).

**Done when:** the new tests and the three existing suites pass.

### T2: The dispatcher answers `--version` and routes contract verbs before any heavy import (AC1)

**Depends on:** T1
**Mode:** TDD (subprocess and in-process tests)

**Tests:**
- `tests/cli/test_dispatch.py::test_version_prints_distribution_version`: subprocess `-m agentic_inquiry.cli --version`; stdout equals `importlib.metadata.version("agentic-inquiry")`; stderr empty; exit 0; no heavy module.
- `::test_legacy_flags_still_route_to_the_mcp_entry`: with `agentic_inquiry.mcp.cli.main` monkeypatched, `sys.argv = ["ai", "--transport", "stdio", "--project-id", "x"]` reaches it.
- `::test_contract_branches_keep_stderr_silent`: `capabilities` in a subprocess produces empty stderr, also with an unknown `INQUIRY_FOO_BAR=1` exported.
- Contract test `test_help_lists_the_contract_verbs` (in `tests/integration/test_afp_lifecycle_contract.py`): `--help` output names `capabilities`, `integration`, `mcp` and `status`; the `ai status --help` assertion is `test_status_help_has_no_db_option`, owned by T10.

**Approach:**
- Move `from agentic_inquiry.cli.client import connect_or_setup` into the two branches that use it. Add branches `--version`/`-V`, `capabilities`, `integration`, `mcp`, `status` at the top of `main()`; install a `logging.NullHandler` on the root logger there so no library log record reaches stderr through `lastResort` (diagnostics travel in `errors[]`); `logging.basicConfig(INFO)` moves off module import onto the interactive branches. The legacy route for other leading flags is unchanged. `print_help()` gains the four verbs.

**Done when:** the tests pass and `ai --help` lists `capabilities`, `integration`, `mcp` and `status`.

### T3: Request parsing, response building, rendering and budget accounting match the schemas (AC5, AC7, AC8, AC18 to AC22, AC24)

**Depends on:** T0 (the schemas the tests validate against)
**Mode:** TDD

**Tests:**
- `tests/unit/integration/test_contract.py`: admitted keys exactly; every bound in AC8 at the boundary value and one past it, mapped to its code and to its envelope or content class, including the `metadata` key count, key pattern, reserved keys, value types and sizes; `finalize` returns `inert` with a `durable_store_absent` error and `partial` with `budget_exhausted`, `partial` for a `committing` row and for a `queued` receipt whose row is `committed` only when another row is open, and `error` only for an explicit refusal; `bound_response` keeps the refusal first, keeps the first 16 errors in gate order, exempts `data.file_path` from the 256-byte cut and drops an entry whose path exceeds it into `omitted`; `owner` missing or unknown; `project_root` canonical rule (relative, alias symlink, `..`, trailing slash, file); `event_id` and `session_id` length and printable-ASCII charset; observation shape (`content` required, `summary` 1024, `importance` range); hypothesis property that `ContextBudget.fit` never exceeds the budget and that `omitted` plus fitted entries equals the input; the ledger-key encoding gives distinct keys for `("X:Stop:Y", "Z")` and `("X", "Y:Stop:Z")`; `render_text` opens with the data-not-instructions line, wraps entries with provenance delimiters alone on their lines, emits header values from the safe charset only (a planted file named with `>>`, a newline and a decoy `<<evidence` header renders with balanced frames and an opener matching the AC21 regex), interleaves spaces into every run of two or more `<` or `>` in content so `<<<` and `>>>` leave no `<<` or `>>` (asserted as a post-condition over the rendered text), and cuts to 256 bytes on a UTF-8 boundary (a 4-byte character spanning byte 256 survives without an exception); `bound_response` drops `entries` then whole frames from the end of `text`, re-deriving `used` and `omitted`, so the worst-case response (32 entries, 8 receipts, 16 errors each with a 256-byte `path`, 50 pending, `context_budget` 16384) serialises under 32768 bytes with `used == len(text.encode())` intact, and 16 `artifact_ignored` errors whose relative forms exceed 256 bytes carry no `path`; `value + "\n"` fails every pattern; no response string is an absolute path; `finalize` implements the AC5 precedence for every status combination; no error message contains an absolute path.
- `::test_response_and_capabilities_shapes_match_schemas`: every builder output validates with `jsonschema`; `::test_request_schema_agrees_with_the_parser`: for every AC8 bound, the boundary payload validates against `afp-lifecycle-hook-request.schema.json` and parses, and the one-past payload fails both (a trailing newline in `session_id`, `event_id` or a `metadata` key, an unknown observation key, an empty `content` and one wrong-type payload per admitted key, included; the one-past payloads are ASCII so bytes and code points coincide).

**Approach:**
- `agentic_inquiry/integration/contract.py` (a draft in the tree is rewritten against the reviewed clauses, not extended): `EVENTS`, `CLIENT_EVENTS`, `STATUSES`, `RECEIPT_KINDS`, `HOOK_ERROR_CODES`, `CLI_ERROR_CODES`, `ADVISORY_CODES`, `MAX_HOOK_INPUT_BYTES`, `IDENTITY_PATTERN`, `HookRequest.parse(payload, client, event)` split into `parse_envelope` (pre-binding) and `parse_content` (post-binding), `ContractError(code, message, **fields)`, `new_response()`, `finalize(response, refusal) -> exit code`, `ContextBudget`, `render_text(entries)` (each entry carries its own `owner`, `client` and `created` from its ledger row), `bound_response(response)`.

**Done when:** unit and property tests are green and the schemas validate the fixtures.

### T3b: The reused validators reject a trailing newline (AC8, AC13 fullmatch clause)

**Depends on:** none
**Mode:** TDD

**Tests:**
- `tests/unit/mcp/test_validation_fullmatch.py`: `validate_project_id("demo\n")` raises; `validate_project_id("demo")` returns `demo`; the existing validation tests stay green.

**Approach:**
- `agentic_inquiry/mcp/utils/validation.py`: `re.match(pattern, ...)` with `^...$` becomes `re.fullmatch`, a one-line fix in the blessed helper the integration reuses.

**Done when:** the new test passes and `tests/unit/mcp` stays green.

### T3c: The FTS query builder sanitises on its retry branch too (AC19)

**Depends on:** none
**Mode:** TDD

**Tests:**
- `tests/unit/database/test_query_builder_retry_sanitises.py`: with a stale-table error forced on the first `table.search`, the retried search receives the sanitised query, not the raw one.

**Approach:**
- `agentic_inquiry/database/query_builder.py`: `safe_query = _fts_sanitizer.sanitize(query)` is hoisted into `fts_search`'s own scope beside `filter_expression`, so both `_run_search` and `_retry_search` close over it (a `safe_query` local to `_run_search` alone leaves the retry raising `NameError`); the test asserts the retried call returns rows, not only that it received the sanitised text.

**Done when:** the test passes and the existing query-builder tests stay green.

### T4: The ledger stores bindings, events and notifications with idempotent semantics (AC6, AC10 to AC14, AC16, AC24, AC27)

**Depends on:** none
**Mode:** TDD

**Tests:**
- `tests/unit/integration/test_state.py`: `record_event` (one `INSERT ... ON CONFLICT(key) DO UPDATE SET deliveries = deliveries + 1 RETURNING ...` statement) returns `new`, then `duplicate` with `deliveries == 2` and the stored receipt, then `conflict` for a different `input_hash`; `pending(limit=50)` returns newest first with the total; `mark(key, "committed", receipt)` updates the receipt; `notify_once` true then false; `read_identity` accepts the grammar, refuses a malformed file, a non-hex id and a file over 4096 bytes; `records_path` refuses an id that fails the pattern and resolves under `~/.agentic-inquiry` when `INQUIRY_HOME` is unset; `binding_for(identity, client, project_root)` yields inert for a missing or disabled row, `durable_store_absent` when the database file is missing, and `project_identity_invalid` when the stored root differs; `purge` removes events and notifications and keeps bindings, and after it the captured observation text is absent from the bytes of `records.sqlite3` and of every `records.sqlite3-wal`; a `session_id` of `x'; DROP TABLE integration_events; --` round-trips as data; marker read and write round-trip; `purge_rows` removes only `purged` rows and leaves a tombstone with the row's kind for each, `tombstone_for(key)` answers after the rows are gone, and tombstones older than 48 hours are dropped by `sweep_tombstones()`; two processes writing concurrently under WAL both succeed.

**Approach:**
- `agentic_inquiry/integration/state.py` (a draft in the tree is rewritten against the reviewed clauses, not extended; a `reset_for_retry` that zeroes `attempts` is the shape to avoid) using `sqlite3` (synchronous: the hook is a short-lived process and an event loop on the hot path buys nothing), `PRAGMA user_version`, schema creation on first open, `records_path(identity)` under `INQUIRY_HOME`, `ProjectFiles` for `project.toml` and `integration.json`, `open_ledger(path, *, timeout, read_only=False)`, `recent_captures(identity, owner, enabled_clients, rows=20)` (capture rows with a payload, newest first), `null_payloads(identity)` (AC27 step zero), `project_lock(identity, *, shared, timeout)` over `fcntl.flock` on `INQUIRY_HOME/projects/<id>/lock` (opened `O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC`, mode `0o600`, `os.fstat` regular-file-and-owner check, never unlinked; shared with a 30 s wait for `reconcile` and 0 s when the tick calls it, exclusive with `--wait` for `purge`; `EWOULDBLOCK`/`EAGAIN` are busy, any other `OSError` is a refusal naming the errno), `claim_row(key)`, `append_memory_id(key, lease, memory_id)` and `mark_claimed(key, lease, state, result)` (the AC17 compare-and-swaps, every one guarded on the lease, the lease written by SQLite's `strftime`), `ledger_home(identity)` resolving `INQUIRY_HOME` once, opening it, `projects/` and `projects/<id>/` with `O_DIRECTORY | O_NOFOLLOW`, creating them `0o700`, tightening an owned directory with `os.fchmod` on CLI verbs only when the loose bits are read or execute, refusing another owner, a non-directory, a failed chmod or a group or other write bit (`project_files_invalid` on the CLI with path, check and remedy in the message; on a hook `ledger_unavailable` for a foreign owner, a non-directory or a write bit, proceeding on a read or execute bit and never healing), opening the database `O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC` with mode `0o600` on the CLI and without `O_CREAT` or `fchmod` on a hook (`ENOENT` is the absent store), checking `os.fstat` (regular file, own uid, one link) before `sqlite3.connect`, `ProjectFiles` refusing a symlinked (`os.lstat`) or escaping (`validate_file_path`) `.agentic-inquiry`, `project.toml` or `integration.json` (`project_files_invalid`), creating `project.toml` with `O_EXCL | O_NOFOLLOW` and the marker through `tempfile.mkstemp(dir=...)`, fsync and `os.replace`, binding functions `upsert_binding`, `binding_for` (which validates the stored namespace and reads a missing or unparseable policy as all false with budget 0), `set_enabled`, and `purge` (connection with `secure_delete = ON` before the deletes, then `VACUUM` and `wal_checkpoint(TRUNCATE)`; `purge` first returns the committed capture rows' memory item ids, the CLI deletes them through `MemorySystem.delete`, and only when every delete succeeded does `purge_rows` remove the `purged` rows, writing each key and kind into `integration_tombstones`; `sweep_tombstones()` deletes those older than 48 hours and runs at the start of `enable`, `disable`, `reconcile` and `purge`; a failed delete leaves the rows, exits 1 and reports `memories_failed`).

**Done when:** the unit tests pass, including the concurrent-writer test.

### T5: `ai capabilities --json` reports the contract (AC2)

**Depends on:** T2, T3
**Mode:** TDD for `capabilities()`; goal-based for the subprocess contract test

**Tests:**
- Contract test AC2 (subprocess, schema validation, every pinned value, timing).
- Unit: `capabilities()` derives the client table from `CLIENT_EVENTS` and the `runtime` table is the literal truth table from AC2.

**Approach:**
- `agentic_inquiry/integration/capabilities.py` (a draft in the tree is rewritten against the reviewed clauses, not extended); `--json` accepted and default.

**Done when:** AC2 passes.

### T6: `enable`, `disable`, `status` and `purge` manage bindings with owner and identity rules (AC10 to AC13, AC25, AC27, AC28)

**Depends on:** T2, T3, T4
**Mode:** TDD for the binding functions; goal-based for the subprocess contract tests

**Tests:**
- Contract tests AC10 (including `test_enable_refuses_a_symlinked_marker` with an in-project target and the healing of a `0o755` ledger home, `test_enable_refuses_a_ledger_home_that_is_not_a_directory`, and the mode assertions), AC27's declined confirmation (`test_purge_without_yes_needs_an_exact_affirmative`), AC12's permitted owner change (`test_owner_changes_after_disable_and_purge`), AC10's refusals (`test_unregistered_clone_on_a_hostile_ledger_home_is_not_inert`; `test_ledger_home_with_a_write_bit_is_refused_with_a_remedy`: a `0o770` home refuses `project_files_invalid` on the CLI and `ledger_unavailable` on a hook, both messages naming the path and `chmod go-w`; a hard-linked `records.sqlite3` refuses with the copy-and-replace remedy), AC11, AC12 (CLI parts other than the freeze test, which T9 owns), AC13 (enable part), AC25 (`status` policy report), AC27 (`test_purge_removes_events_and_keeps_bindings`, `test_purge_refuses_while_a_committer_holds_the_lock` and the refusal cases; `test_purge_removes_committed_memories_from_recall` needs recall and reconcile and belongs to T8), AC28 (`integration status`).
- Unit: `enable` refuses `project_not_onboarded` when `resolve_environment(workspace=project_root).config_path` is `None` or lies outside the project (a global environment), naming `ai setup local ai --workspace <p>`; a repeat `enable` without `--no-capture` re-enables capture; refuses `storage_namespace_invalid` when the environment's `storage.default_project_id` is missing, empty or fails `validate_project_id`; refuses a `--context-budget` above 16384; refuses `standalone_plugin_enabled` from `.claude/settings.json` and `settings_unreadable` when that file is a symlink out of the project, over 1 MiB, or not JSON; refuses `project_identity_invalid` for a copied identity bound to another root, as do `disable`, `reconcile` and `purge` for a `--project-root` that is not the stored root; `purge` takes the exclusive lock before any change and refuses `environment_busy` with nothing changed while a shared lock is held (`--wait` bounds the wait), then under the lock nulls every payload and marks the rows `purged` with `secure_delete`, `VACUUM` and a truncating checkpoint before the first memory delete, and prints the bound root; `INQUIRY_HOME/projects/<id>/` is `0o700` and `records.sqlite3` `0o600` after `enable` whatever the umask; `enable --owner standalone` on a disabled `afp` binding with rows refuses `owner_conflict`; `enable`, `disable` and `purge` each drop a tombstone seeded with an `erased_at` older than 48 hours; a verb monkeypatched to raise prints `{"ok": false, "errors": [{"code": "internal_error"}]}`, exit 1, empty stderr, and a ledger that cannot be read within the busy timeout prints `environment_busy` naming the errno; records the environment's `storage.default_project_id`; prints exactly the two gitignore lines; records the raw namespace after `validate_project_id(value, normalize=False)` and snapshots the environment's `connectors.filesystem.ignore_patterns` into the policy; `disable` prints the purge command; `purge --yes` deletes the committed memory items by id through `MemorySystem.delete` first (a `False` return counts as already deleted) plus every item whose `task_id` equals a purged ledger key (batches of `batch_size`, 100 from the CLI, each deleted before the next query, at most 1000 batches; a unit test calls the purge function with `batch_size=2` over five items reachable only through `task_id` and sees all five deleted in three queries, and with a delete that leaves rows visible sees it stop after the bound with `memories_failed` and the count deleted so far), calls `compact_tables` and `cleanup_old_versions` with the two memory table names, a zero retention window and `delete_unverified=True` (the parameter threaded through `cleanup_old_versions` in `agentic_inquiry/database/lancedb_manager.py` for this call site; a per-table `error` is `memories_failed`, a missing table is not), then removes the `purged` rows into tombstones and empties notifications, and reports `{project_root, events, notifications, memories}`; with a monkeypatched delete that raises it leaves the rows, exits 1 and reports `memories_failed` with `memories` counting the ids deleted before the raise; a sixth item stored with an unrelated `task_id` in the same namespace survives the `batch_size=2` sweep; an item promoted to the semantic table by consolidation (the same id in two tables) is removed from both by one purge; after `consolidate()` has run over captured observations, `purge` leaves no `consolidation_engine` row whose `agent_id` is a purged binding's `<owner>:<client>:<identity>` composite, including one stored with `task_id=None` and `source_items` naming only unpurged ids and one stored under a different `project_id`; a `consolidation_engine` row of another project's composite survives; with `batch_size=2` over five concept rows the sweep deletes all five in three queries.

**Approach:**
- `agentic_inquiry/cli/integration.py` and the verb module (a draft in the tree is rewritten against the reviewed clauses, not extended; a concept sweep that filters `source_items` in Python and returns success without progressing is the shape to avoid) (argparse subcommands `hook`, `enable`, `disable`, `status`, `reconcile` with `--retry <durable_id>`, `--force` and `--lock-wait <seconds>`, `purge`; `--json` on every verb but `hook`; one `except Exception` per verb that prints the `internal_error` envelope, `sqlite3.OperationalError` on open or read mapped to `environment_busy`, and any other `sqlite3.DatabaseError` mapped to `project_files_invalid` with the move-aside remedy); binding logic in `state.py`; policy flags `--no-recall`, `--no-capture`, `--no-refresh`, `--context-budget`; `purge --wait <seconds>`; the settings check opens `project_root/.claude/settings.json` only after `validate_file_path` confirms a regular file inside the project and its size is at most 1 MiB.

**Done when:** the listed contract tests pass.

### T7: The hook orchestrator answers inert, owner, identity, policy and queued capture correctly (AC4 to AC9, AC12 to AC16, AC20, AC24 to AC26)

**Depends on:** T5, T6
**Mode:** TDD for the gate functions; goal-based for the subprocess contract tests

**Tests:**
- Contract tests AC4, AC5, AC6, AC7, AC8, AC9 (escape, `artifact_ignored`, a missing and a directory artifact dropped, every artifact dropped without an `event_id` not refused, the same under `--no-refresh` not `refresh_disabled`, a FIFO artifact dropped without blocking, an unreadable `chmod 000` artifact dropped (skipped as root), and a ledger overwritten with non-SQLite bytes answering `ledger_unavailable` (`partial`, exit 1 on a SessionStart; refusal, exit 2 on a Stop with observations; the CLI half of `test_corrupt_ledger_degrades_like_an_unreadable_one`, `project_files_invalid` with the move-aside remedy, belongs to T6), AC12 (hook part), AC13 (hook part), AC14, AC15, AC16, AC20, AC24, AC25 (`capture_disabled`, `refresh_disabled`), AC26 (ledger-only part).
- Unit: handler table maps events to ledger-only or read-capable; deadline defaults 6.0, 3.0 and 0.5 for SessionEnd, with the env override accepted only as a float in `(0, 600]` and otherwise ignored; `runtime` block present on every path including the exception path; `internal_error` produced when a handler raises.

**Approach:**
- `agentic_inquiry/integration/hooks.py` (any draft of this module in the tree predates the reviewed clauses and is rewritten against them, not extended): `hook(client, event, stdin, *, deadline=None) -> tuple[dict, int]` reading at most 1048577 bytes; `cli/integration.py` hands `hook`'s argv to a hand-rolled parser (`parse_hook_argv(argv) -> tuple[str | None, str | None]`) so argparse never prints usage for it; the artifact exclusion floor (`EXCLUSION_FLOOR` in `contract.py`, a literal tuple matched case-insensitively with `fnmatch.fnmatchcase` over casefolded values against the confinement-resolved project-relative path, its basename and every path component; the ledger row stores that resolved form), the binding policy's `ignore_patterns` snapshot, a NUL-byte sniff of the first 8 KiB and the 2 MiB size cap are applied at the gate with no connector or config import; per-event handlers as private functions; `error.path` for `artifact_escape` is the request's pre-resolution in-project relative form or omitted; `sqlite3.DatabaseError` (busy, locked, not a database, malformed) on a ledger open, read (the binding gate included, never `inert`) or write inside the deadline becomes `ledger_unavailable`, advisory when the request carried no observations and no artifacts and a refusal otherwise, always `notify: true`; a top-level `except Exception` that returns `internal_error` naming only the exception type and writes nothing to stderr; `bound_response()` then `finalize()` before serialisation.

**Done when:** the listed contract tests pass.

### T8: SessionStart and UserPromptSubmit return bounded, framed recall and evidence (AC18, AC19, AC21, AC23, AC25 recall part, AC26)

**Depends on:** T7, T9 (the contract tests reconcile before they recall)
**Mode:** goal-based (integration tests against a real LanceDB environment)

**Tests:**
- Contract tests AC18 (25 seeded rows, the newest present and the oldest absent), AC19 (including an indexed file deleted before the query, whose entry is omitted), AC21, AC23 (`INQUIRY_HOOK_DEADLINE_SECONDS=1` on UserPromptSubmit forces the skip), AC25 (`--no-recall`), AC26 (SessionStart part), and `test_purge_removes_committed_memories_from_recall` (recall before and after a purge).
- Unit (`tests/unit/integration/test_state.py`): `recent_captures(identity, owner, enabled_clients, rows=20)` returns capture rows only, of that owner and those clients, with a payload, newest first by `created_at` then insertion order, in any state, and never more than `rows`; `render_text` escapes before it cuts, so 256 `<` render as a body under 256 bytes with no `<<`; a locked ledger (a second connection holding `locking_mode=EXCLUSIVE`) makes SessionStart return `partial` with `ledger_unavailable` inside the deadline and Stop with observations return `error` exit 2 with nothing recorded.

**Approach:**
- SessionStart recall in `hooks.py` through `state.recent_captures(identity, owner, enabled_clients, rows=20)` (SQL `WHERE project_id = ? AND kind = 'capture' AND owner = ? AND client IN (...) AND payload IS NOT NULL ORDER BY created_at DESC, rowid DESC LIMIT 20`), each observation rendered by `render_text` with id `<durable_id>.<index>`, owner and client from the row, body `summary` or `content` escaped then cut, at most 32 observations, empty `text` when nothing renders; no store import on that path. UserPromptSubmit evidence in a `_read_stage` that imports `Config` and `StorageFacade` lazily, guarded by the remaining deadline, via `facade.fts_search(query, limit=5, project_id=storage_project_id)`; entries rendered by `render_text`.

**Done when:** the listed contract tests pass and SessionStart stays heavy-import free under AC26.

### T9: `reconcile` commits queued captures and refreshes, re-confines paths and records failures (AC17)

**Depends on:** T7
**Mode:** goal-based (integration tests against a real LanceDB environment) plus TDD for the failure branches

**Tests:**
- Contract test AC17 including the vanished-file branch, a run with one failed row (`ok: true`, exit 1, `failed == 1`) driven to exhaustion (three runs, then `events.exhausted == 1`, SessionStart `ok` with a `capture_exhausted` advisory, `--retry` making it claimable again with `attempts` monotonic and `resets == 1` (and `resets == 0` on every never-reset row), a stale or non-exhausted `--retry` id resetting nothing, a third reset refused with `policy_invalid` and accepted with `--force`, `--retry` against a copied identity refused before any write, and an artifact replaced by a FIFO between the hook and the run closed as `artifact_ignored` without blocking), the multi-observation row (three ids in `result.memory_ids`), the exit code and the `--json` envelope with `skipped`, `exhausted` and `rows`; the AC12 freeze test (`test_disable_freezes_queued_rows_until_enable_or_purge`); `reconcile` on a disabled binding skips and lists its rows; `reconcile --project-root` on a copied identity refuses `project_identity_invalid`.
- `tests/cli/test_memory_exit_code.py` stays green with its monkeypatch target moved to `create_memory_system`.
- Unit (`tests/unit/integration/test_reconcile.py`): a parse failure marks the row `failed` with `attempts` incremented; a row at 3 attempts is counted in `exhausted`; a stored path that now escapes or ends in a symlink is never read and is marked `failed` with `artifact_escape`; a stored path whose reconcile-time re-resolution differs from the stored form (an intermediate component became a symlink after the hook) is never read and is marked `failed` with `artifact_escape`; a re-resolved path matching the exclusion floor or the snapshot patterns is closed as `committed` with `result.outcome: artifact_ignored` without a read; rows are drained oldest first; rows in `pending`, `committing` and `failed` below 3 attempts are all selected; a `committing` row whose recorded ids the tier layers' `get_by_id` all find is completed without a second store; a `committing` row of three observations with one id recorded and one more item found by `task_id` stores only the third index (by `observation_index`) and then commits with three ids; a `purged` row is skipped and counted in `skipped`; a run over 101 claimable rows with `limit=100` commits 100 and reports `remaining == 1`; tombstones older than 48 hours are gone after a run; a committer whose lease was stolen (the row re-claimed by another committer) fails its next append or its terminal mark, leaves its items for the winner's `task_id` recovery, and reports the row lost; a loser whose row was purged deletes its items; two committers in two processes never commit the same row; under `loop.set_default_executor(ThreadPoolExecutor(max_workers=8))` with a warm pool neither `reconcile` nor `purge` raises `sqlite3.ProgrammingError` and every claimed row reaches a terminal mark; a path swapped for a symlink to a file outside the project between the `fstat` and the parse is never followed (the bytes come from the held descriptor); an item another process stored before the winner's claim is adopted, not duplicated, even when the winner's connection was opened earlier; a row whose commit exceeds 30 s is marked `failed` with result `timeout`; the exclusion floor, size cap and binary filter are re-checked before any read.

**Approach:**
- Rename `agentic_inquiry/cli/memory.py:_create_memory_system` to `create_memory_system`, switch its three internal callers and the existing test's monkeypatch target to the new name in the same commit; no new memory module.
- `agentic_inquiry/integration/reconcile.py` (same rule: a draft in the tree is rewritten against the reviewed AC17): `async def reconcile(project_root, *, client=None, limit=100, lock_timeout=30.0) -> dict` (reporting `remaining` and `lost`), wrapped with `asyncio.run` at the CLI boundary and awaited by the maintenance tick, holding `project_lock(identity, shared=True, timeout=lock_timeout)` for the run (`environment_busy` otherwise; the tick passes `lock_timeout=0`), calling every synchronous `state.py` function through `asyncio.to_thread` so the server's event loop never blocks on a ledger busy timeout, calling `sweep_tombstones()` first, claiming each row through `claim_row` before touching the store and skipping a row whose claim updates nothing, appending ids through `append_memory_id` and marking through `mark_claimed`, both guarded on the lease, and on a lost lease deleting its own items only when the re-read row is gone or `purged`, and skipping rows whose `owner` differs from the binding's (counted in `skipped`); the memory system is constructed after each claim through a `LanceDBManager` whose `ConnectionManager` receives the existing zero-argument `connection_factory=lambda: lancedb.connect(uri, read_consistency_interval=timedelta(0))` closing over the resolved uri (`agentic_inquiry/database/connection.py:62`), and `invalidate_table_cache` is called for the two memory tables, so the recovery lookups see other processes' committed writes; `pyproject.toml` gains the upper bound `lancedb>=0.8.0,<0.26` in the same commit; runtime-owned metadata keys (`event_key`, `event`, `project_identity`, `observation_index`) are applied after the caller's, which the request gate already refuses; captures through one `MemorySystem.store(content, context=create_agent_context(agent_id=f"{owner}:{client}:{identity}", session_id, conversation_id=session_id, task_id=key, project_id=storage_project_id), importance=max(0.7, obs.importance if obs.importance is not None else 0.7), metadata={..., "event_key": key, "event": event, "project_identity": identity, "observation_index": index})` per observation, appending each id to `result.memory_ids` before the next store; refreshes by re-checking the artifact through the `O_NOFOLLOW | O_NONBLOCK` descriptor, closing it, and handing the canonical absolute path to the base's own update path (parser chain by name, `reindex_document`, `flush_pending_relationships`, `file_tracker.update_hash`, or `remove_file_data` by absolute path when the file is gone, receipt `indexed`), the residual check-to-open window recorded in AC17; every ledger call opens, uses and closes its connection inside one `asyncio.to_thread` call; `--lock-wait <seconds>` (default 30) bounds the shared-lock wait; `mark` per row.

**Done when:** AC17 and the unit tests pass.

### T10: `ai status` and `ai mcp` exist and the maintenance tick drains the ledger (AC28, AC29)

**Depends on:** T6, T9
**Mode:** TDD for dispatch; goal-based for `status --json` shape and the tick's ledger transition

**Tests:**
- Contract test AC28 (`ai status --json`).
- `tests/cli/test_dispatch.py::test_mcp_dispatches_with_the_storage_namespace`: `agentic_inquiry.mcp.cli.main` monkeypatched; argv carries `--project-id <storage namespace> --project-root <root> --transport stdio`; `--project-id X` overrides; without a binding the argv carries neither `--project-id` nor `--project-root`.
- `tests/integration/test_integration_maintenance_tick.py`: a pending row becomes `committed` with a `remembered` receipt after one call of the tick body against the fixture environment.

**Approach:**
- `agentic_inquiry/cli/status.py`; `mcp` branch in `__main__.py` resolving the binding for the current directory's project root; `agentic_inquiry/mcp/cli.py` gains `--project-root` (optional) and threads it through `run_server(config, project_id, transport, host, port, project_root=None)` and `MCPServer.__init__(..., project_root=None)` into `create_mcp_services(config, project_id, project_root=None)`; the loop body is extracted into an awaitable `_maintenance_tick(memory_system, storage, project_root)` coroutine that the `while True` loop awaits, so the test drives one tick; the tick calls `reconcile(project_root, lock_timeout=0)` when it is set and takes no lock of its own; when the lock is held the run refuses `environment_busy`, which the tick logs at WARNING and skips (a test holds the exclusive lock and asserts the tick returns without committing); `test_status_help_has_no_db_option` is owned here.

**Done when:** the three tests pass.

### T11: Every REST bind site goes through `bind_host` and defaults to loopback (AC30)

**Depends on:** none
**Mode:** TDD for `bind_host`; goal-based for the bind sites

**Tests:**
- `tests/unit/mcp/test_server_bind.py`: `MCPServer.run(transport="http", host=None)` and `MCPServer.run_async(transport="http", host=None)` with `mcp.api.host = "0.0.0.0"` raise before any socket opens whatever the auth setting (the FastMCP run monkeypatched).
- `tests/server/test_bind.py`: `bind_host(None, auth_enabled=False) == "127.0.0.1"`; `bind_host("localhost", False) == "localhost"`; `bind_host("127.0.0.1", False)` and `bind_host("::1", False)` return the address; `bind_host("0.0.0.0", False)`, `bind_host("::", False)`, `bind_host("::ffff:0.0.0.0", False)` and `bind_host("not-an-address", False)` raise `ValueError` naming the auth requirement or the parse failure; `bind_host("0.0.0.0", True)` returns it; the MCP call sites re-raise with a message naming the reverse-proxy recipe, not the API key.
- `tests/server/test_entrypoint.py`: `scripts/entrypoint.py` run as a subprocess with `INQUIRY_SERVER_HOST=0.0.0.0` and no API key exits 1 with a message naming `INQUIRY_SERVER_HOST` and the API-key setting, without a traceback.
- `! grep -q "0\.0\.0\.0" agentic_inquiry/server/run.py agentic_inquiry/server/lifecycle.py agentic_inquiry/mcp/cli.py agentic_inquiry/mcp/server.py && test "$(grep -o '0\.0\.0\.0' scripts/entrypoint.py | wc -l)" -eq "$(grep -o 'INQUIRY_SERVER_HOST=0\.0\.0\.0' scripts/entrypoint.py | wc -l)"` exits 0 (every occurrence in the entrypoint is the documented token); `tests/server/test_lifecycle.py` and `tests/unit/mcp` stay green.

**Approach:**
- New `agentic_inquiry/server/bind.py` with `bind_host(requested: str | None, auth_enabled: bool) -> str` using `ipaddress.ip_address(...).is_loopback`; `run.py`, `lifecycle.py` (both the bind default and the health URLs), `scripts/entrypoint.py` (reading `INQUIRY_SERVER_HOST` with no default, exiting 1 with the two settings named when `bind_host` refuses), the `Dockerfile` (`ENV INQUIRY_SERVER_HOST=0.0.0.0` beside `PORT`, with the API-key setting documented) and both `MCPServer.run` and `MCPServer.run_async` in `mcp/server.py` (the requested host or the `config.mcp.api.host` fallback, with `auth_enabled=False`, before the socket opens) call it; `auth_enabled` comes from the respective auth config and requires a configured key; fix the log line in `run.py`.

**Done when:** the unit tests pass, the grep is empty and the suite passes.

### T12: Documentation and status close out (AC31)

**Depends on:** T1 to T11
**Mode:** goal-based

**Tests:**
- `lint-spec-status.py` exits 0; the link check over the touched docs passes; `grep -q INQUIRY_HOOK_DEADLINE_SECONDS docs/guides/reference/lifecycle-cli.md && grep -q event_id_conflict docs/guides/reference/lifecycle-cli.md && grep -q memories_failed docs/guides/reference/lifecycle-cli.md && grep -q '"ok": false' docs/guides/reference/lifecycle-cli.md`; `grep -q "CLI verb" docs/CHARTER.md && grep -q "to_thread" docs/CHARTER.md && grep -q "to_thread" AGENTS.md`; `git diff --quiet main -- CHANGELOG.md`; `! grep -q "0\.0\.0\.0\|10\.0\.0\.0/8" docs/mcp/configuration.md docs/mcp/troubleshooting.md docs/mcp/security.md && ! grep -q "10\.0\.0\.0/8" docs/mcp/deployment.md && test "$(grep -o '0\.0\.0\.0' docs/mcp/deployment.md | wc -l)" -eq "$(grep -o 'INQUIRY_SERVER_HOST=0\.0\.0\.0' docs/mcp/deployment.md | wc -l)"` (every occurrence in the deployment page is the container recipe token); `grep -q "no other writer" docs/guides/reference/lifecycle-cli.md && grep -q "network-mounted" docs/guides/reference/lifecycle-cli.md && grep -q "48 hours" docs/guides/reference/lifecycle-cli.md && grep -q "scoped to this" docs/guides/reference/lifecycle-cli.md && grep -q "weak verifier" docs/guides/reference/lifecycle-cli.md && grep -q "4096" docs/guides/reference/lifecycle-cli.md && grep -q "chmod go-w" docs/guides/reference/lifecycle-cli.md`; `grep -q withdrawn docs/mcp/deployment.md && grep -q withdrawn docs/mcp/security.md && grep -q sidecar docs/mcp/deployment.md && grep -q "serves nothing without both" docs/mcp/deployment.md && grep -q "serves nothing without both" Dockerfile`; `grep -q "bind loopback only in 0.3.0" <page>` for each of the four MCP pages; `grep -q records.new docs/guides/reference/lifecycle-cli.md && grep -q capture_exhausted docs/guides/reference/lifecycle-cli.md && grep -q -- --retry docs/guides/reference/lifecycle-cli.md && grep -q -- --force docs/guides/reference/lifecycle-cli.md && grep -q project_files_invalid docs/guides/reference/lifecycle-cli.md && grep -q ledger_unavailable docs/guides/reference/lifecycle-cli.md`; `grep -q 'lancedb>=0.8.0,<0.26' pyproject.toml`; `grep -q "binds to 127.0.0.1 by default" <page> && grep -q "a non-loopback bind requires an API key" <page>` for each of the four MCP pages; `grep -q '^version = "0.3.0"' pyproject.toml`; `grep -q "lifecycle contract" docs/CHARTER.md`; `grep -q "agentic_inquiry/integration/" AGENTS.md`; `grep -q "AFP pack" README.md && grep -q "never both enabled" README.md`; `test -f docs/architecture/integration.md && grep -q "integration.md" docs/architecture/README.md && grep -q "architecture/integration.md" docs/README.md`; `grep -q INQUIRY_SERVER_HOST scripts/entrypoint.py && grep -q INQUIRY_SERVER_HOST Dockerfile && grep -q INQUIRY_SERVER_HOST docs/mcp/deployment.md`; `python -m agentic_inquiry.cli --help | grep -q capabilities`.

**Approach:**
- `docs/architecture/integration.md` plus rows in `docs/architecture/README.md`, `docs/README.md`, `AGENTS.md`; `docs/guides/reference/lifecycle-cli.md`; `docs/mcp/deployment.md`, `docs/mcp/configuration.md`, `docs/mcp/troubleshooting.md` and `docs/mcp/security.md` rewritten to the loopback default, the auth requirement, the reverse-proxy recipe and `INQUIRY_SERVER_HOST`; `README.md` step 2 "Option B" and CLI list; `docs/CHARTER.md` delivery surfaces, Principle 2 and the Principle 4 ledger exception (as RFC-0002 accepted and its errata record); `AGENTS.md` async bullet; `docs/backlog.md` section kept current; ADR-0005 to Accepted; `pyproject.toml` 0.3.0.

**Done when:** the checks pass and every AC but AC32 is `[x]`.

### T13: The AFP pack journey is recorded (AC32)

**Depends on:** T12, and AFP pack `agentic-inquiry` 0.3.0 installed in a scratch repository
**Mode:** visual / manual QA

**Tests:**
- `docs/specs/afp-lifecycle-contract/notes/afp-pack-journey.md` exists and records, for SessionStart, UserPromptSubmit, PostToolUse (Write), PreCompact and Stop (with an observation, exercising the pack's synthesised `event_id`): the payload sent through `afp-runtime/plugin_hooks.py --client claude-code`, the bridge's stdout, the runtime's exit code, the receipts, and `ai status --json` before and after `ai integration reconcile`.

**Approach:**
- `uv tool install` the runtime (with the operator's consent), `afp bundle install --pack agentic-inquiry --scope repo --adapter claude-code` in a scratch git repository, `ai setup local ai --workspace <repo>`, `ai integration enable --client claude-code --owner afp`, replay the payloads, record everything, then uninstall.

**Done when:** the note exists with real output and the spec's status moves to Shipped.

## Rollout

- **Delivery:** big bang inside version 0.3.0; inert by default. Nothing changes for a project until an operator runs `ai integration enable`. Rollback is `ai integration disable`; the ledger stays for inspection and `purge` removes it. T3b tightens the shared `validate_project_id` so a project id with a trailing newline is refused for every MCP caller too; no caller passes one today.
- **Breaking change:** the MCP http and sse transports can no longer bind a non-loopback address (AC30); operators who exposed port 8765 on a LAN or in a container move to the reverse-proxy recipe in `docs/mcp/security.md`, and the REST server binds non-loopback only with an API key. The release note names it.
- **Infrastructure:** none. State is local files under `INQUIRY_HOME` and two files in the project.
- **External-system integration:** the AFP pack (`packs/agentic-inquiry` 0.3.0) must accept `claude-code`, call `capabilities` only at SessionStart, inject `context.text` only, honour the notify rule, and synthesise a stable `event_id` for any observation-bearing event whose native payload carries none (`sha256(client, session_id, event, sha256(observations))`), otherwise every such Stop is refused with `event_id_required`; it ships from the AFP repository in the same change set.
- **Deployment sequencing:** runtime first (`uv tool install`), then the pack, then `ai integration enable` per project.

## Risks

- The base's `Config.load()` may touch LanceDB during validation; the hook path loads config only inside the guarded read stage. Mitigation: import hygiene tests on the ledger-only paths.
- `pytest-randomly` and pre-existing failures in the suite (knowledge entry K-0001) can mask regressions. Mitigation: run the new suites alone first, then the full suite with `-p no:randomly`, and compare failing sets to `main`.
- Cold caches make SessionStart recall miss its budget. Mitigation: the deadline guard returns `partial` instead of a late answer; thresholds are warm-run values.
- The maintenance tick only drains while an `ai mcp` server runs; a Claude Code user without the MCP entry accumulates pending rows. Mitigation: every response lists them, `ai status` counts them, and the pack skill can run `reconcile`.

## Changelog

- 2026-09-22: initial plan. Compared with the session plan approved earlier the same day, reconcile no longer runs inside SessionStart and PreCompact: the embedding model alone costs about 6.5 s warm, so an in-hook commit cannot fit the budget. Commitment moves to `ai integration reconcile` and the MCP server's maintenance tick, and hooks report `pending` honestly.
