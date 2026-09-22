---
name: onboard
description: Intelligently onboard a codebase - parallel index, explore, and validate. Use when setting up ai for a new codebase or helping someone get started.
argument-hint: "[path] [--env local|postgres|gcp|aws|azure] [--skip-index] [--deep]"
context: fork
agent: general-purpose
allowed-tools: Bash, Read, Write, Glob, Grep, Agent, AskUserQuestion
---

# /ai:onboard

Intelligent codebase onboarding. Runs indexing in background while exploring the codebase structure, saving memories, detecting gaps, and validating everything works.

## Your Task

Onboard the codebase at: **$ARGUMENTS** (default: current directory)

## Project Context

- Current directory: !`pwd`
- Project files: !`ls -la`
- Git status: !`git log --oneline -5 2>/dev/null || echo "Not a git repo"`
- Existing ai config: !`cat .agentic-inquiry/env-registry.json 2>/dev/null || echo "No ai environment configured"`

## Phase 1: Environment Setup

The onboard command **must ensure a working environment** before proceeding.

**Decision tree:**

| Condition | Action |
|-----------|--------|
| `--env` flag provided | Use that environment, validate it |
| Active environment in registry | Show it, ask user to confirm or create new |
| No registry / no environments | Ask user: Which storage backend? |

If no usable environment exists, spawn the env-manager agent to create one.

**Do NOT proceed to Phase 2 until connectivity is confirmed.**

## Phase 2: Parallel Execution

### 2.1 Record onboard run start

```bash
ai onboard start
```

Capture the printed `ONBOARD_RUN_ID=...` value for Phase 4.

### 2.2 Start indexing in background

Launch indexing as a background Agent:
```
Agent tool:
  run_in_background: true
  prompt: Index the codebase using: ai index {path}
```

### 2.3 Explore codebase structure (foreground)

While indexing runs, spawn the **codebase-explorer** agent to:
1. Map languages, frameworks, tech stack
2. Identify architecture patterns and layers
3. Trace data flow paths
4. Detect gaps where ai indexing may fall short
5. **Save memories throughout exploration** (not just at the end):

```bash
ai memory save "Architecture: {finding}"
ai memory save "Pattern: {pattern}"
ai memory save "Key entity: {entity} - {purpose}"
```

## Phase 3: Post-Index Validation

After indexing completes:
- Validate key entities found by explorer appear in search results
- Trace lineage paths identified during exploration
- Verify gaps are real

## Phase 4: Record completion, report, and memories

```bash
ai onboard complete --run-id {ONBOARD_RUN_ID}
```

Generate comprehensive onboarding report with:
- Quick summary table (languages, architecture, entities, gaps)
- Architecture map
- Data flow paths
- Saved memories list
- Recommended next commands

## Options

| Option | Description |
|--------|-------------|
| `path` | Directory to onboard (default: `.`) |
| `--env` | Environment to use (local, gcp, or env name) |
| `--skip-index` | Skip indexing, just explore and validate |
| `--deep` | Extra exploration depth (default for onboarding) |
