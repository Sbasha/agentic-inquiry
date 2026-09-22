# Spec: First-run reliability

> Historical reference. This page describes PostgreSQL-family providers, cloud connectors or remote embedders that are not part of this local-only distribution. It is retained as design input for the external provider contract in [storage-backends.md](../../storage-backends.md).

- **Status:** Implementing
- **Owner:** sbasha
- **Plan:** [`plan.md`](plan.md)
- **Constrained by:** none
- **Brief:** none
- **Discovery:** none
- **Contract:** none
- **Shape:** mixed

Mode: full (multi-feature dependent tasks, new public CLI surface, secrets and
file I/O on the env-file loader).

## Objective

A user who installs `ai`, runs `/ai:setup` with the local (LanceDB)
backend, then indexes a project gets a working index without hitting a
dead-end gate, a silent empty success, a storm of retryable write
failures, or a missing env file. Optional secrets and operator pins
(`INQUIRY_EMBEDDING_DEVICE=cpu`) live in `.agentic-inquiry/envs/<name>/.env` and load
automatically. `ai index` exits 0 only when indexing actually produced
chunks.

## Boundaries

### Always do

- Treat a missing onboard run as a warning, not a block, so first index
  after setup proceeds.
- Exit `ai index` with code 1 unless status is `completed` and
  `chunks_created > 0`.
- Retry only LanceDB write errors whose message marks them retryable
  (`commit conflict` or `Retryable`), with a capped backoff (5 attempts).
- Load `.agentic-inquiry/envs/<name>/.env` from the resolved environment directory
  only; confine the resolved path under that directory via
  `validate_file_path`; never overwrite a variable already set in the
  process environment; never log values.

### Ask first

- Re-enable a hard onboard gate that blocks indexing.
- Default every Mac install to `INQUIRY_EMBEDDING_DEVICE=cpu` (uncommented).
- Add a cross-process LanceDB lock instead of (or in addition to) retry.

### Never do

- Add a new top-level dependency (including `python-dotenv`).
- Add a new top-level package or module boundary beyond
  `agentic_inquiry/cli/onboard.py` as a sibling of the other CLI command
  modules.
- Write or read the target project's own `.env` (project root).
- Convert Gemini or Codex mirrors, or make `/ai:onboard` a Python
  explorer (it stays an agent skill).

## Testing Strategy

- Gate warning vs block, index exit-code mapping, LanceDB retry filter,
  and dotenv load/confine/override rules: **TDD**. Each is a
  compressible invariant.
- Local setup creating `.agentic-inquiry/envs/<name>/.env`, Claude onboard skill no
  longer probing project-root `.env`, and `ai onboard` appearing in
  `--help`: **goal-based check** (`grep` / file exists after `LocalSetup.run`).
- `ai onboard start` then `ai onboard complete` on a temp workspace,
  and `ai index` on a fixture that yields 0 chunks exiting 1: **visual /
  manual QA** of the built CLI.

## Acceptance Criteria

- [x] Given a project with no onboard run, `ai index` proceeds (warning
      only). `OnboardGateError` is not raised for `reason == "no_onboard"`.
      MCP `index_files` does not return `status: blocked` solely because
      onboard is missing.
- [x] `ai onboard start` prints a run id and persists a pending run;
      `ai onboard complete --run-id <id>` marks that run completed and
      latest. `/ai:onboard` calls both around the background index.
- [x] `exit_code_for_index_result` returns 0 only for status `completed`
      with `chunks_created > 0`; `completed_with_errors`,
      `all_files_failed`, `partial_failure`, `failed`, `no_files_found`,
      and empty (`chunks_created == 0`) results return 1. `ai index`
      uses that helper and still prints the summary.
- [x] `_upsert_rows` and `_add_rows` retry errors whose text contains
      `commit conflict` or `Retryable`, up to 5 attempts with
      exponential backoff. Schema and permission errors are not retried.
- [x] `LocalSetup.run` writes `.agentic-inquiry/envs/<name>/.env` containing a
      commented `INQUIRY_EMBEDDING_DEVICE=cpu` line. Success text tells the
      operator to uncomment it if Metal/MPS indexing aborts.
- [x] `load_config_for_environment` loads that env file before YAML and
      `AI_*` overlays. Missing file is a no-op. Existing `os.environ`
      keys win. Values are not logged. The resolved `.env` path must
      stay inside the environment directory (`validate_file_path` with
      that directory as `allowed_base`).
- [x] Claude ai skills do not `cat` or otherwise read a project-root
      `.env`. Onboard skill current-state probes use `.agentic-inquiry/` only.

## Assumptions

- Technical: `create_onboard_run` / `complete_onboard_run` exist on
  `OnboardMetadataService` and have no production Claude caller
  (source: `agentic_inquiry/onboard/metadata_service.py`; Gemini
  `extensions/gemini/ai/commands/ai/onboard.toml` is the only
  production closer; `get_latest_run` requires `is_latest` and
  `status = 'completed'`).
- Technical: `ai index` always `return 0` after printing results
  (source: `agentic_inquiry/cli/index.py`).
- Technical: LanceDB `_upsert_rows` / `_add_rows` wrap all failures as
  `StorageError` with no retry (source:
  `agentic_inquiry/database/lancedb_manager.py`). `RetryPolicy` already
  exists (`agentic_inquiry/utils/retry.py`).
- Technical: globally installed `ai` does not load dotenv; Azure setup
  already writes `.agentic-inquiry/envs/<name>/.env` (source: no `load_dotenv` in
  `agentic_inquiry/`; `agentic_inquiry/cli/setup/azure_setup.py`).
- Product: missing onboard is a warning, not a block; env file lives
  only under `.agentic-inquiry/envs/<name>/.env` (source: user confirmation
  2026-09-04).
- Process: Gemini/Codex mirrors stay out of scope, same carve-out as
  skill-global-invocation (source: user confirmation 2026-09-04 via
  approved plan).

## Declined patterns

Tempted to add `python-dotenv`; declining - KEY=VALUE parsing is a few
lines and a new dependency is forever. Tempted to force CPU embeddings
on Darwin; declining - 4-8x slower, the hatch stays commented. Tempted
to add a cross-process LanceDB lock manager; declining - retry matches
the error class the database already labels retryable.
