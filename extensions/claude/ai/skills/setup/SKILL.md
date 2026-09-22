---
name: setup
description: Configure Agentic Inquiry storage backend (LanceDB, PostgreSQL, GCP, AWS, or Azure). Use when setting up ai for the first time or changing storage backends.
argument-hint: "[local|postgres|gcp|aws|azure] [project-name]"
disable-model-invocation: true
allowed-tools: Bash, Read, Write, AskUserQuestion
---

# /ai:setup

Configure Agentic Inquiry storage and create a new project.

The `ai` command must already be on PATH (the user ran `uv tool install .`
from the agentic-inquiry clone). Run it in **this** project directory. Do not
`cd` into the agentic-inquiry clone, do not use `uv run`, and do not ask where
the workspace should live - it is the current project.

## Your Task

Set up ai with: **$ARGUMENTS**

## Current State

- Existing environments: !`cat .agentic-inquiry/env-registry.json 2>/dev/null || echo "No environments"`
- Existing env config: !`ls .agentic-inquiry/envs/*/config.yaml 2>/dev/null || echo "No environment config"`

## Storage Options

| Option | Backend | Best For | Setup Time |
|--------|---------|----------|------------|
| `local` | LanceDB | Development, testing | Instant |
| `postgres` | PostgreSQL | Self-managed DB | 2-5 min |
| `gcp` | Cloud SQL | GCP Production | 5-10 min |
| `aws` | RDS | AWS Production | 5-10 min |
| `azure` | Azure DB | Azure Production | 5-10 min |

## Selection Requirement

**CRITICAL:** If the user has not specified a backend in `$ARGUMENTS`, you MUST use the `AskUserQuestion` tool to let them choose. Do NOT assume a default backend.

## What Gets Created

**Local Setup:**
```
.agentic-inquiry/env-registry.json              # Environment registry
.agentic-inquiry/envs/<name>/config.yaml        # Storage configuration
.agentic-inquiry/envs/<name>/lancedb/           # Local vector store
```

**Cloud Setup:**
- Managed Database instance configuration
- Cloud Proxy configuration (if applicable)
- `config/postgresql.yaml` or equivalent

## Environment Variables

The local (LanceDB) default embeds with a local `sentence_transformer`
model and needs **no API key**. Only set an embedding key if you
explicitly switch to a hosted embedder (e.g. OpenAI):

```bash
# Optional - only if you switch to a hosted embedder:
OPENAI_API_KEY=sk-...           # Not needed for the local default

# Database settings (for non-local backends only):
POSTGRES_HOST=localhost
POSTGRES_DB=agentic-inquiry
POSTGRES_USER=ai
POSTGRES_PASSWORD=<generated>
```

## After Setup

```bash
ai index . --project-id <project-name>
ai search "main entry point" --project-id <project-name>
```
