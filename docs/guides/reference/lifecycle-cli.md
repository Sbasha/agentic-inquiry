# Lifecycle CLI

The AFP pack and an operator drive Agentic Inquiry through the `ai` command.
A hook calls two verbs. An operator uses the rest.

## Setup

`ai setup` creates the project-local LanceDB environment, the same store `agv setup` creates, and then offers to enable lifecycle hooks. On a terminal it asks before it writes. `ai setup --client claude-code` enables that client with no prompt. `ai setup --no-enable` and `ai setup --dev` leave hooks off. The enable step calls `ai integration enable --owner afp`. Commit `.agentic-inquiry/project.toml`. Leave `integration.json` untracked.

After it finishes, index, serve, and search are the next commands, as they are after a local Agent Vault setup. Start a new client session so the installed hooks see the binding.

## Verbs

| Verb | Who calls it |
|------|----------------|
| `ai --version` | Anyone. One line, the distribution version. |
| `ai capabilities --json` | The pack, once, at SessionStart. |
| `ai integration hook --client <claude-code\|codex\|pi> --event <event>` | The pack, on every lifecycle event. JSON on stdin, one JSON object on stdout. |
| `ai integration enable --client <c> --owner <afp\|standalone> --project-root <p>` | An operator. Creates the ledger. A hook never does. |
| `ai integration disable` | An operator. Leaves the ledger in place. |
| `ai integration status --json` | An operator. Bindings and event counts. |
| `ai integration reconcile` | An operator, or the MCP maintenance tick. Commits queued rows. |
| `ai integration purge` | An operator. Erases retained rows. |
| `ai status --json` | An operator. Project, integration counts, and index sizes. |
| `ai mcp` | An operator. stdio MCP server. Its maintenance tick calls reconcile. |

Events: `SessionStart`, `UserPromptSubmit`, `PostToolUse`, `PreCompact`, `Stop`, `SessionEnd`. `TaskCompleted` is unsupported.

## Two code sets

Hook responses use the closed set in `contracts/jsonschema/afp-lifecycle-hook-response.schema.json`. Codes an operator sees there include `ledger_unavailable`, `capture_exhausted`, `event_id_conflict`, `artifact_ignored`, `durable_store_absent`, and `budget_exhausted`.

CLI verbs use `project_not_onboarded`, `storage_namespace_invalid`, `standalone_plugin_enabled`, `settings_unreadable`, `owner_conflict`, `owner_mismatch`, `project_identity_invalid`, `project_files_invalid`, `policy_invalid`, `memories_failed`, `environment_busy`, `confirmation_declined`, and `internal_error`.

A corrupt `records.sqlite3` is `ledger_unavailable` on a hook and `project_files_invalid` on the CLI. The CLI message names the file. The hook message does not name an absolute path.

## CLI envelope

With `--json`, success is `{"schema_version": 1, "ok": true, ...}`. Refusal is:

```json
{"schema_version": 1, "ok": false, "errors": [{"code": "project_files_invalid", "message": "..."}]}
```

Exit 0 is ok or inert. Exit 1 is partial, unsupported, or a CLI refusal. Exit 2 is a hook error. `reconcile` with `failed > 0` prints `"ok": true` and exits 1.

## Deadlines

`SessionStart` and `UserPromptSubmit` have 6.0 seconds. `SessionEnd` has 0.5 seconds. Every other event has 3.0 seconds. `INQUIRY_HOOK_DEADLINE_SECONDS` overrides a deadline when it is a float in `(0, 600]`. Evidence is skipped when fewer than 2.5 seconds remain. SessionStart recall is never skipped for budget.

## Capture, retry, purge

Capture is queued. `ai integration reconcile` and the MCP maintenance tick commit it. Reconcile does not run inside `SessionStart` or `PreCompact`.

A row that fails three times is exhausted. SessionStart reports `capture_exhausted` and names `--retry`. `ai integration reconcile --retry <durable_id>` moves that row back to pending and increments `resets`. Attempts stay monotonic. A third `--retry` without `--force` is `policy_invalid`. `--force` allows one more reset.

`ai integration purge` prints the project root, states that no other writer (`ai index`, `ai memory save`, an MCP tool call, a server) is running, and proceeds only on the exact answer `yes` unless `--yes` is passed. Tombstones live at least 48 hours and are deleted by the next operator verb that opens the ledger for writing. Ledger erasure is scoped to this `INQUIRY_HOME`: another machine or worktree enabled against the same committed `project.toml` keeps its own copies. After purge, the content columns are cleared. The row key remains a weak verifier for clients that derive `event_id` from content. `event_id_conflict` is not returned over erased content.

The AFP pack applies a 4096-byte ceiling to injected context. `project.toml` is also at most 4096 bytes.

## Ledger home

`INQUIRY_HOME` (or `~/.agentic-inquiry`) holds `projects/<id>/records.sqlite3`. The marker `<project>/.agentic-inquiry/integration.json` is a hint. The SQLite binding is the authority.

A directory with a group or other write bit is refused. Inspect it, then `chmod go-w` on that path. A hard-linked database is refused with:

```bash
cp records.sqlite3 records.new && mv records.new records.sqlite3
```

The project lock's mutual exclusion is not guaranteed on a network-mounted `INQUIRY_HOME`.
