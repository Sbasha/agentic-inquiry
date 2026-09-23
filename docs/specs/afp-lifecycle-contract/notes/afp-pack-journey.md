# AFP pack journey

Evidence for AC32. Scratch repository `~/projects/assets/afp-inquiry-e2e`. Pack `agentic-inquiry` 0.3.0, installed at repo scope for the claude-code adapter. Runtime `ai` 0.3.0 from `~/.local/bin/ai` after `uv tool install . --reinstall`. Claude Code, Codex, and Pi were not opened. Codex and Pi stay deferred to native qualification.

The bridge is the projected `afp-runtime/plugin_hooks.py`. Each event is one call with `--client claude-code`. That process runs the projected `hooks/inquiry-lifecycle.py`. The hook's exit code is the one the bridge observes. The pack does not print the inner `ai integration hook` process exit code.

Project identity `7a41a1d9e7894970`. Session `journey-20260922`.

## Setup

`afp bundle install --pack agentic-inquiry --adapter claude-code --scope repo` exited 0:

```
installed: agentic-inquiry @ repo via claude-code
```

Install state records version 0.3.0. The projected `afp-runtime/plugin.json` name is `agentic-inquiry` and version is `0.3.0`.

`ai setup local ai --workspace ~/projects/assets/afp-inquiry-e2e` exited 1. The local environment was already present at `.agentic-inquiry/envs/ai/config.yaml` (LanceDB, `embeddings.default_provider: sentence_transformer`).

`ai integration enable --client claude-code --owner afp` exited 0 and printed:

```
.agentic-inquiry/*
!.agentic-inquiry/project.toml
```

## Payloads

Plugin root: `~/projects/assets/afp-inquiry-e2e/.agents/plugins/agentic-inquiry/claude-code`.

Command shape:

```
python3 <plugin-root>/afp-runtime/plugin_hooks.py --plugin-root <plugin-root> --client claude-code --event <event>
```

Stdin for each event:

SessionStart

```json
{"cwd": "/Users/sammy.a.basha/projects/assets/afp-inquiry-e2e", "session_id": "journey-20260922"}
```

UserPromptSubmit

```json
{"cwd": "/Users/sammy.a.basha/projects/assets/afp-inquiry-e2e", "session_id": "journey-20260922", "prompt": "Where is greet defined?"}
```

PostToolUse (Write of `app.py`). No `event_id`. The pack derives one from the tool use and the file.

```json
{"cwd": "/Users/sammy.a.basha/projects/assets/afp-inquiry-e2e", "session_id": "journey-20260922", "tool_name": "Write", "tool_input": {"file_path": "app.py"}, "tool_use_id": "toolu_journey_write_app"}
```

PreCompact

```json
{"cwd": "/Users/sammy.a.basha/projects/assets/afp-inquiry-e2e", "session_id": "journey-20260922"}
```

Stop. No `event_id`. The observation is the bytes the pack hashes into a stable id.

```json
{"cwd": "/Users/sammy.a.basha/projects/assets/afp-inquiry-e2e", "session_id": "journey-20260922", "observations": [{"content": "greet in app.py returns the string hello", "importance": 0.9}]}
```

## Bridge and hook

| Event | Bridge exit | Hook exit | Hook stdout |
| --- | --- | --- | --- |
| SessionStart | 0 | 0 | `{}` |
| UserPromptSubmit | 0 | 0 | `{}` |
| PostToolUse | 0 | 0 | receipts: 1 (`refresh:e2af60d55221400d2f0184294629c12f114cb7cc427166c35896f603b9a67905`); pending: 1; errors: 0 |
| PreCompact | 0 | 0 | receipts: 0; pending: 1; errors: 0 |
| Stop | 0 | 0 | receipts: 1 (`capture:b900518802acda41f026310fbe34838354ab12ff7f2f42019ae39b755fbea073`); pending: 2; errors: 0 |

Hook stderr was empty on every event. SessionStart and UserPromptSubmit added no inquiry context: the index was empty, so the hook printed `{}` and the bridge kept only its own plugin text.

Bridge stdout, SessionStart (exit 0):

```json
{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "Installed plugin agentic-inquiry: /Users/sammy.a.basha/projects/assets/afp-inquiry-e2e/.agents/plugins/agentic-inquiry/claude-code. Project: /Users/sammy.a.basha/projects/assets/afp-inquiry-e2e. Resolve its skills, agents and supporting resources relative to this installed plugin root.\nPlugin workflow identity for explicit skill dispatch: {\"session_id\": \"journey-20260922\"}. Copy these native identifiers unchanged into this turn's Skill workflow receipt."}}
```

Bridge stdout, UserPromptSubmit (exit 0):

```json
{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "Plugin workflow identity for explicit skill dispatch: {\"session_id\": \"journey-20260922\"}. Copy these native identifiers unchanged into this turn's Skill workflow receipt."}}
```

Bridge stdout, PostToolUse (exit 0):

```json
{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "receipts: 1 (refresh:e2af60d55221400d2f0184294629c12f114cb7cc427166c35896f603b9a67905); pending: 1; errors: 0"}}
```

Bridge stdout, PreCompact (exit 0):

```json
{"hookSpecificOutput": {"hookEventName": "PreCompact", "additionalContext": "receipts: 0; pending: 1; errors: 0"}}
```

Bridge stdout, Stop (exit 0):

```json
{"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": "receipts: 1 (capture:b900518802acda41f026310fbe34838354ab12ff7f2f42019ae39b755fbea073); pending: 2; errors: 0"}}
```

## Status and reconcile

`ai status --json` before the five events, exit 0:

```json
{"schema_version": 1, "ok": true, "version": "0.3.0", "project": {"root": "/Users/sammy.a.basha/projects/assets/afp-inquiry-e2e", "id": "7a41a1d9e7894970"}, "integration": {"project_id": "7a41a1d9e7894970", "storage_project_id": "default", "bindings": [{"client": "claude-code", "owner": "afp", "enabled": true, "policy": {"recall": true, "capture": true, "refresh": true, "context_budget": 2048}}], "events": {"pending": 0, "committed": 0, "failed": 0, "exhausted": 0, "purged": 0}, "schema_version": 1}, "index": {"chunks": 0, "entities": 0, "relationships": 0}}
```

`ai status --json` after the five events and before reconcile, exit 0. Pending is 2. The index is still empty:

```json
{"schema_version": 1, "ok": true, "version": "0.3.0", "project": {"root": "/Users/sammy.a.basha/projects/assets/afp-inquiry-e2e", "id": "7a41a1d9e7894970"}, "integration": {"project_id": "7a41a1d9e7894970", "storage_project_id": "default", "bindings": [{"client": "claude-code", "owner": "afp", "enabled": true, "policy": {"recall": true, "capture": true, "refresh": true, "context_budget": 2048}}], "events": {"pending": 2, "committed": 0, "failed": 0, "exhausted": 0, "purged": 0}, "schema_version": 1}, "index": {"chunks": 0, "entities": 0, "relationships": 0}}
```

`ai integration reconcile --project-root ~/projects/assets/afp-inquiry-e2e` exited 0. Stdout:

```json
{"schema_version": 1, "ok": true, "committed": 2, "failed": 0, "skipped": 0, "exhausted": 0, "lost": 0, "remaining": 0, "rows": [{"durable_id": "refresh:e2af60d55221400d2f0184294629c12f114cb7cc427166c35896f603b9a67905", "kind": "refresh", "state": "committed", "attempts": 1, "resets": 0, "result": {"outcome": "indexed", "memory_ids": []}}, {"durable_id": "capture:b900518802acda41f026310fbe34838354ab12ff7f2f42019ae39b755fbea073", "kind": "capture", "state": "committed", "attempts": 1, "resets": 0, "result": {"outcome": "remembered", "memory_ids": ["0393c6b7-35c5-4bbe-9d8e-3bf1e94bf30a"]}}]}
```

Stderr carried an unauthenticated Hugging Face Hub warning, a one-line weight-load progress mark (`103/103`), and a `resource_tracker` warning about one leaked semaphore at shutdown.

`ai status --json` after reconcile, exit 0. Pending is 0, committed is 2, chunks 2, entities 2:

```json
{"schema_version": 1, "ok": true, "version": "0.3.0", "project": {"root": "/Users/sammy.a.basha/projects/assets/afp-inquiry-e2e", "id": "7a41a1d9e7894970"}, "integration": {"project_id": "7a41a1d9e7894970", "storage_project_id": "default", "bindings": [{"client": "claude-code", "owner": "afp", "enabled": true, "policy": {"recall": true, "capture": true, "refresh": true, "context_budget": 2048}}], "events": {"pending": 0, "committed": 2, "failed": 0, "exhausted": 0, "purged": 0}, "schema_version": 1}, "index": {"chunks": 2, "entities": 2, "relationships": 0}}
```
