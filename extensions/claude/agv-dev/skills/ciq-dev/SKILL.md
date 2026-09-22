---
name: agv-dev
description: Development mode toggle. Use when developing/testing agv to isolate test data from production. Auto-loads when user mentions dev mode or test isolation.
user-invocable: false
---

# agv Dev Mode Skill

Toggle between isolated test environment and normal production use.

## When to Use

- "I want to test agv changes"
- "Don't pollute my real index"
- "Set up a dev environment"
- "Am I in dev mode?"

## The Problem

When developing or testing agv, you don't want to:
- Corrupt your real search index
- Mix test memories with real insights
- Accidentally use experimental data in production

## The Solution

Dev mode creates a complete isolation layer:

```
Normal Mode                    Dev Mode
─────────────                  ─────────
.agv/            .agv/dev/
├── lancedb/        ──vs──     ├── lancedb/
├── memories/                  ├── memories/
└── config.yaml                └── config.yaml
```

## Workflow

### Enter Dev Mode

```bash
/agv-dev:dev on
```

Creates:
- `.agv/.dev-mode` marker file
- `.agv/dev/` directory with isolated storage
- Sets `agv_PROJECT_ID=agv-dev`

### Work in Dev Mode

All agv commands now use the dev environment:
- `/agv:index` → indexes to dev storage
- `/agv:search` → searches dev index
- `/agv:memory save` → saves to dev memories

Banner displays each turn:
```
[agv DEV MODE] Using test environment. `/agv-dev:dev off` to exit.
```

### Exit Dev Mode

```bash
/agv-dev:dev off
```

- Removes `.dev-mode` marker
- Returns to normal environment
- Banner stops displaying

## Check Mode

```bash
/agv-dev:dev status
```

Shows:
- Current mode (dev/normal)
- Environment path in use
- Index stats for current environment

## How the Banner Works

A `UserPromptSubmit` hook checks for `.agv/.dev-mode`:
- If exists: prints `[agv DEV MODE]` banner
- If absent: no output

This ensures you always know which environment you're using.

## Tips

1. **Always check status** before important work
2. **Use dev mode** when testing agv changes
3. **Exit dev mode** when done testing
4. **Dev data persists** - you can `/agv-dev:dev on` later and continue
