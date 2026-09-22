# Plan: First-run reliability

- **Spec:** [`spec.md`](spec.md)
- **Status:** Done

## Approach

Four independent seams on the same first-run path, implemented in order
so each is testable alone: soften the onboard gate and add a thin record
CLI, map index results to exit codes, retry retryable LanceDB writes,
then bootstrap and auto-load `.agentic-inquiry/envs/<name>/.env`. No new libraries.
Retry uses existing `RetryPolicy`. Path confinement uses existing
`validate_file_path`.

Riskiest part: dotenv loading must not leak values or escape the env
directory, and retry must not swallow schema errors.

## Constraints

- No RFC: first-run bug fixes, not a charter or convention change.
- `Never do` in the spec: no `python-dotenv`, no project-root `.env`,
  no Gemini/Codex conversion.

## Construction tests

**Integration tests:** none beyond per-task tests. The four seams do not
share a single new integration surface.

**Manual verification:** `ai onboard start` / `complete` on a temp
workspace; `ai index` summary still prints when exit code is 1.

## Design (LLD)

### Design decisions

- Missing onboard warns instead of raising `OnboardGateError`. Traces
  to AC 1. Alternative (skip-flag only from the onboard skill) left the
  README setup-then-index path blocked.
- Exit 0 only for `completed` + `chunks_created > 0`. Traces to AC 3.
- Retry at `_upsert_rows` / `_add_rows` via `RetryPolicy`, matching
  `commit conflict` / `Retryable` on the original exception text.
  Traces to AC 4.
- Env file is always `config_path.parent / ".env"`. Traces to AC 5-6.

### Interfaces & contracts

Public CLI: `ai onboard start [--project ID] [--artifact-path PATH]`
prints `ONBOARD_RUN_ID=<uuid>`. `ai onboard complete --run-id ID`
marks completed. Traces to AC 2. No OpenAPI contract.

`exit_code_for_index_result(result: Mapping[str, Any]) -> int` in
`agentic_inquiry/cli/index.py`. Traces to AC 3.

### Component / module decomposition

- `agentic_inquiry/cli/onboard.py` - new sibling CLI module, same shape as
  `memory.py`.
- `load_environment_dotenv` in `env_resolver.py`.
- Retry helper next to `_upsert_rows` in `lancedb_manager.py`.
- Gate change stays in `gate.py`.

### Failure, edge cases & resilience

- Missing `.env`: no-op.
- Unreadable `.env` or path outside env dir: log warning, do not load,
  continue (optional file, not a security control that must fail closed
  on the CLI).
- Retry cap 5; non-retryable errors raise immediately.
- Dotenv values never interpolated as commands; `KEY=VALUE` only.

### Quality attributes (NFRs)

- Secrets: never log dotenv values (lazy logging with key names only).
- Path confinement: `validate_file_path(env_file, allowed_base=env_dir)`.
- Retry bounded (exceptional-conditions: no unbounded retry).

## Tasks

### T1: Missing onboard is a warning; `ai onboard start|complete` records runs

**Depends on:** none

**Touches:** agentic_inquiry/onboard/gate.py, tests/onboard/test_gate.py, agentic_inquiry/cli/onboard.py, agentic_inquiry/cli/__main__.py, extensions/claude/ai/skills/onboard/SKILL.md

**Tests:**
- `test_gate_warns_when_no_onboard` (replaces
  `test_gate_blocks_when_no_onboard`): `check_onboard_gate` returns a
  result with `reason == "no_onboard"` and does not raise.
- `test_gate_allows_skip` still passes.
- Goal-based: `ai --help` text includes `onboard`. Skill file contains
  `ai onboard start` and `ai onboard complete` and does not contain
  `cat .env`.

**Approach:**
- In `check_onboard_gate`, log a warning for `no_onboard` and return
  `staleness` (same control flow as stale).
- Add `agentic_inquiry/cli/onboard.py` wrapping
  `OnboardMetadataService.create_onboard_run` /
  `complete_onboard_run`. Wire `onboard` in `__main__.py` like `memory`.
- Update onboard skill: start before background index, complete at end;
  drop the project-root `.env` probe.

**Done when:** gate tests green; skill grep checks pass; `ai onboard
start --help` exits 0.

### T2: `ai index` exits 1 unless indexing produced chunks

**Depends on:** none

**Touches:** agentic_inquiry/cli/index.py, tests/cli/test_index_exit_code.py

**Tests:**
- Parametrized `exit_code_for_index_result`: `completed` + chunks 10 ->
  0; `completed` + chunks 0 -> 1; `completed_with_errors` -> 1;
  `all_files_failed` -> 1; `failed` -> 1; `no_files_found` -> 1;
  `partial_failure` -> 1.

**Approach:**
- Add `exit_code_for_index_result` in `index.py`. Replace `return 0`
  after the summary with `return exit_code_for_index_result(result)`.

**Done when:** `tests/cli/test_index_exit_code.py` is green and
`index_command` calls the helper.

### T3: Retry retryable LanceDB commit conflicts

**Depends on:** none

**Touches:** agentic_inquiry/database/lancedb_manager.py, tests/database/test_lancedb_retry.py

**Tests:**
- `_is_retryable_lancedb_error`: `commit conflict` and `Retryable`
  true; schema / permission / unrelated StorageError false.
- `_upsert_rows` (or the inner write) fails twice with retryable, succeeds
  on third; call count 3. Non-retryable raises on first call.

**Approach:**
- Extract `_is_retryable_lancedb_error(exc)`. Wrap the write+flush in
  `_upsert_rows` and `_add_rows` with `RetryPolicy(max_attempts=5,
  base_delay=0.1, jitter=True)` and a predicate that inspects the
  original exception (and `__cause__`).

**Done when:** `tests/database/test_lancedb_retry.py` is green.

### T4: Bootstrap and auto-load `.agentic-inquiry/envs/<name>/.env`

**Depends on:** none

**Touches:** agentic_inquiry/cli/env_resolver.py, agentic_inquiry/cli/setup/local_setup.py, tests/cli/test_env_resolver.py, tests/cli/setup/test_local_setup.py, extensions/claude/ai/skills/onboard/SKILL.md

**Tests:**
- Missing file: `load_environment_dotenv` is a no-op.
- File with `FOO=bar` sets `os.environ["FOO"]` when unset.
- Existing `os.environ["FOO"]` is not overwritten.
- Comments and blank lines ignored; values never appear in log messages.
- Path outside env dir (symlink escape) is not loaded.
- `LocalSetup.run` creates `.env` containing commented
  `AI_EMBEDDING_DEVICE=cpu`.

**Approach:**
- `load_environment_dotenv(env_dir)` parses KEY=VALUE, called from
  `load_config_for_environment` after resolve, before `Config.load`.
- `LocalSetup` writes the file and mentions the Metal hatch in next
  steps.
- Confirm onboard skill has no project-root `.env` probe (may already
  be done in T1).

**Done when:** env-resolver and local-setup tests green;
`rg 'cat \\.env' extensions/claude/ai/skills/` is empty.

## Rollout

Big bang in one PR. Reversible by revert. No schema migration, no infra,
no flag. Existing indexes keep working; first-time users gain the new
paths.

## Risks

- Softening the gate means a user can index forever without onboard
  docs. Mitigated by the warning and by the skill recording a run.
- Retry delay can slow a persistently conflicted writer. Cap is 5
  attempts; remaining failures still surface via index exit code.
- Loading `.env` into `os.environ` is process-global. Mitigated by
  not overwriting existing keys and by loading only the active env
  file.

## Changelog

- 2026-09-04: initial plan from approved first-run reliability plan.
