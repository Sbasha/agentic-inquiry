# ADR-0005: Host integration: a stdlib-only CLI lifecycle contract over plugin-embedded logic

- **Status:** Accepted
- **Date:** 2026-09-22
- **Decision-makers:** sammybasha
- **Supersedes:** none
- **Related:** RFC-0002, ADR-0004, `docs/specs/afp-lifecycle-contract/spec.md`, `contracts/jsonschema/`

## Decision summary

- **Decision:** We expose one client-neutral lifecycle contract on the `ai` command, implemented in `agentic_inquiry/integration/` with stdlib and SQLite only on its hot paths, and every host adapter (the AFP pack first) is a thin translator over it.
- **Because:** a hook that must answer inside a few seconds on every prompt cannot afford the package's import cost or an embedding model, and a contract that lives in the runtime is tested once and reused by every client.
- **Applies to:** `ai --version`, `ai capabilities`, `ai integration hook|enable|disable|status|reconcile|purge`, `ai mcp`, `ai status`, the JSON shapes under `contracts/jsonschema/`, and the import-time behaviour of `agentic_inquiry/__init__.py`.
- **Tradeoff accepted:** hook-time capture is a queued receipt, not a committed memory; commitment happens in `ai integration reconcile` or the MCP server's maintenance tick, so a session can end with work visibly pending.
- **Revisit if:** a client needs synchronous durable capture inside its hook budget, or a measured warm import of the integration package exceeds 0.3 s.

## Context

The AFP pack `packs/agentic-inquiry` is a thin adapter: on each native event it runs `ai integration hook --client <client> --event <event>` with bounded JSON on stdin and expects a JSON response with a status, a context block with byte accounting, receipts with durable identifiers, pending work and errors. It runs `ai capabilities --json` to discover what the runtime supports. Its budgets are 2 s for discovery and about 9 s for a hook call. The runtime's own Claude Code plugin under `extensions/claude/ai/` takes a different route: seven scripts that import the package from the ambient interpreter, talk HTTP to a server they start on demand, and inject instructions into the model on every Stop.

Measured on this workstation (Python 3.13, warm cache): `import agentic_inquiry` takes 1.5 s and loads lancedb, pyarrow and pandas; a stdlib-only interpreter start takes 0.28 s; `import lancedb` alone takes 0.95 s; the sentence-transformer model takes about 6.5 s warm and 34 s cold. The package also creates `.agentic-inquiry/logs` in whatever directory imports it.

Durable state today is CWD-relative and gitignored, so a `git clean -fdx` removes acknowledged memory, and two worktrees of one repository get two memories.

## Decision

We implement the lifecycle contract as a public surface of the `ai` command and make its hot paths independent of the heavy runtime.

- **Surface.** `ai --version`, `ai capabilities [--json]`, `ai integration hook --client {claude-code,codex,pi} --event <event>`, `ai integration enable|disable|status|reconcile|purge`, `ai mcp [--project-id]`, `ai status`. Request, response and capability shapes are JSON Schema documents under `contracts/jsonschema/` at `schema_version` 1 and `hook_schema_version` 1. Adding optional fields keeps the version; removing or renaming a field, changing a status or receipt kind, or changing an exit-code rule bumps it.
- **Hot-path budget.** `agentic_inquiry/__init__.py` performs no I/O and imports no subpackage eagerly. `capabilities`, `integration hook` on the ledger-only paths, `integration status` and `--version` import the standard library and `sqlite3` only. Tests assert wall time and the absence of lancedb, pyarrow, pandas, torch, sentence_transformers, fastmcp, fastapi, fsspec from `sys.modules` on those paths.
- **Durable authority.** A SQLite ledger under `INQUIRY_HOME/projects/<project_id>/records.sqlite3` (WAL) holds bindings, processed events with their input hash and stored receipt, and notification state. Captured observation payloads live in the ledger; memory rows in LanceDB are a derived projection. The project identity is `<project_root>/.agentic-inquiry/project.toml`, meant to be committed; the per-client enablement marker `<project_root>/.agentic-inquiry/integration.json` is machine-local and gitignored.
- **Queued, then reconciled.** A hook never loads the embedding model, never starts a process and never opens a network port. Mutating events write a ledger row and return a `queued` receipt; the captured observations are recallable from the ledger from that moment. `ai integration reconcile`, and the maintenance tick of a running `ai mcp` server, commit queued rows into the memory store and update the stored receipt to `remembered` or `indexed`.
- **Identity and idempotency.** `project_id` is 16 lowercase hex characters validated before any path or query use and bound to the canonical `project_root` recorded at enable time; a request from another root is refused. The ledger key is the SHA-256 of the compact ASCII JSON array `[owner, client, project_id, session_id, event, event_id]`. A redelivery with the same input hash returns the stored receipt with `duplicate: true` and the delivery count; a different input hash is an `event_id_conflict` error, except on a purged or tombstoned key, which answers `event_purged`; a mutating request without `event_id` is refused with `event_id_required`.
- **One owner.** Exactly one owner (`afp` or `standalone`) may be enabled per project and client. A hook from another owner receives `owner_conflict`. Enabling the `afp` owner is refused while the project's `.claude/settings.json` enables the standalone plugin.
- **Data framing.** Recalled memories and evidence are rendered as delimited, provenance-labelled data under a runtime-owned line that says they are not instructions; the whole response is bounded at 32768 bytes and never names a path outside the project.
- **Read paths.** SessionStart recall reads the ledger's capture rows newest first by capture time and never opens the store (the memory adapter applies `limit` before `order_by`, so it cannot answer a recency query exactly). UserPromptSubmit may open the bound LanceDB environment for lexical evidence, guarded by a deadline; a stage that cannot start in time is skipped and reported as `budget_exhausted` with status `partial`.

## Decision drivers

- Measured latency: the hook budget is smaller than the package import, so the contract must not depend on that import.
- One implementation per client behaviour: the AFP bridge dispatches Claude Code, Codex and Pi to the same verb.
- Evidence over assertion: every durable claim has a receipt with an identifier, and a zero exit is never success by itself.
- No implicit process: the pack's own rule, and the preview's `DESIGN.md`, forbid a watcher or server that the user did not start.

## Consequences

**Positive:**

- The AFP pack works against `main` without changing its contract, and Claude Code joins Codex and Pi through the same bridge.
- Import hygiene becomes a tested property of the package, which also speeds every other `ai` command.
- Duplicate delivery is provably harmless through the interface, with a test that delivers the same bytes twice.

**Negative:**

- Capture at hook time is `queued`; a user who never runs `ai mcp` or `ai integration reconcile` accumulates pending rows, visible in `ai status`. Recall still serves them from the ledger, so what waits for reconcile is the memory store (semantic search, consolidation), not the hook's own recall. The spec records this as the honest state.
- The standalone Claude plugin keeps its HTTP mechanics until its own spec migrates it onto this contract; two owners in one project are refused, not merged.
- Hook-path recall is recency and lexical, never semantic, because the model stays out of the hook.
- The ledger retains captured observation text in plain SQLite under `INQUIRY_HOME` until `ai integration purge` runs; `disable` does not delete it. That is the price of durable memory that survives `git clean`, and the purge verb is the operator's control.

**Revisit if:** a client needs synchronous durable capture inside its hook budget, or a measured warm import of the integration package exceeds 0.3 s.

## Confirmation

- **Mode:** lint/CI
- **Signal:** `tests/unit/test_import_hygiene.py` and `tests/integration/test_afp_lifecycle_contract.py` green; the AFP pack's `packs/agentic-inquiry/tests` green against a runtime on PATH.
- **Owner:** sammybasha

## Alternatives considered

- **Wrap the existing Claude plugin (`extensions/claude/ai/`) as the AFP pack.** Rejected against "one implementation per client": it is Claude-only, depends on the ambient interpreter importing the package, starts a server on all interfaces and injects a Stop prompt that turns `/exit` into a model turn.
- **A long-lived local daemon that hooks call over a socket.** Rejected against "no implicit process": it is the Agent Vault daemon pattern the preview's design excluded, it needs lifecycle management the pack cannot own, and it does not remove the import cost, it only moves it.
- **Embed and store memory synchronously inside the hook.** Rejected against measured latency: the model alone exceeds the hook budget.
- **Keep the contract in the pack and have the runtime expose only its existing verbs.** Rejected: the pack would reimplement identity, budgets and receipts per client, and the runtime would have no owner registry.

## References

- `~/projects/assets/afp/packs/agentic-inquiry/.apm/hooks/inquiry-lifecycle.py` and `README.md` for the consumer's expectations.
- `git show 86403f5:src/agentic_inquiry/integration.py` for the preview's implementation of the same contract.
- Claude Code hooks reference, the Language Server Protocol `initialize` handshake and the Model Context Protocol lifecycle for capability negotiation before use (cited in RFC-0002).
