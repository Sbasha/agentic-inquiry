---
name: setup
description: Configure the local Agentic Inquiry storage environment and enable lifecycle hooks. Use when setting up ai for the first time in a project.
argument-hint: "[local] [project-name]"
disable-model-invocation: true
allowed-tools: Bash, Read, Write, AskUserQuestion
---

# /ai:setup

Configure local Agentic Inquiry storage and create a new project.

The `ai` command must already be on PATH (the user ran `uv tool install .`
from the agentic-inquiry clone). Run it in **this** project directory. Do not
`cd` into the agentic-inquiry clone, do not use `uv run`, and do not ask where
the workspace should live - it is the current project.

## Your Task

Run `ai setup` in this project. With no arguments it creates the local LanceDB environment when one is missing, then asks before enabling lifecycle hooks for each AFP client installed here. Pass `--client claude-code` when the person already confirmed that client. Pass `--no-enable` only when they want storage and no hooks.

If `$ARGUMENTS` is set, append it: **$ARGUMENTS**

## Current State

- Existing environments: !`cat .agentic-inquiry/env-registry.json 2>/dev/null || echo "No environments"`
- Existing env config: !`ls .agentic-inquiry/envs/*/config.yaml 2>/dev/null || echo "No environment config"`

## Storage

Agentic Inquiry is local only. The one backend is LanceDB, created instantly with no external dependencies. If `$ARGUMENTS` names anything other than `local`, tell the user that only local storage exists and that an external database for governed projects is future design work.

## What Gets Created

```
.agentic-inquiry/env-registry.json              # Environment registry
.agentic-inquiry/envs/<name>/config.yaml        # Storage configuration
.agentic-inquiry/envs/<name>/lancedb/           # Local vector store
```

## Environment Variables

The local default embeds with a local `sentence_transformer` model and needs
**no API key**. Only set an embedding key if you explicitly switch to a hosted
embedder:

```bash
# Optional - only if you switch to a hosted embedder:
OPENAI_API_KEY=sk-...           # Not needed for the local default
```

## After Setup

The wizard prints the next commands. They match a local Agent Vault setup:

```bash
ai index .
ai serve
ai search "main entry point"
```

When lifecycle enable succeeds, commit `.agentic-inquiry/project.toml` and start a new client session. `integration.json` stays on this machine. Hooks stay inert until that enable step has run.
