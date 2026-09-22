---
name: ai-dev
description: Development mode toggle. Use when developing/testing ai to isolate test data from production. Auto-loads when user mentions dev mode or test isolation.
user-invocable: false
---

# ai Dev Mode Skill

Toggle between isolated test environment and normal production use.

## When to Use

- "I want to test ai changes"
- "Don't pollute my real index"
- "Set up a dev environment"
- "Am I in dev mode?"

## The Problem

When developing or testing ai, you don't want to:
- Corrupt your real search index
- Mix test memories with real insights
- Accidentally use experimental data in production

## The Solution

Dev mode creates a complete isolation layer:

```
Normal Mode                    Dev Mode
─────────────                  ─────────
.agentic-inquiry/            .agentic-inquiry/dev/
├── lancedb/        ──vs──     ├── lancedb/
├── memories/                  ├── memories/
└── config.yaml                └── config.yaml
```

## Workflow

### Enter Dev Mode

```bash
/ai-dev:dev on
```

Creates:
- `.agentic-inquiry/.dev-mode` marker file
- `.agentic-inquiry/dev/` directory with isolated storage
- Sets `INQUIRY_PROJECT_ID=ai-dev`

### Work in Dev Mode

All ai commands now use the dev environment:
- `/ai:index` → indexes to dev storage
- `/ai:search` → searches dev index
- `/ai:memory save` → saves to dev memories

Banner displays each turn:
```
[ai DEV MODE] Using test environment. `/ai-dev:dev off` to exit.
```

### Exit Dev Mode

```bash
/ai-dev:dev off
```

- Removes `.dev-mode` marker
- Returns to normal environment
- Banner stops displaying

## Check Mode

```bash
/ai-dev:dev status
```

Shows:
- Current mode (dev/normal)
- Environment path in use
- Index stats for current environment

## How the Banner Works

A `UserPromptSubmit` hook checks for `.agentic-inquiry/.dev-mode`:
- If exists: prints `[ai DEV MODE]` banner
- If absent: no output

This ensures you always know which environment you're using.

## Tips

1. **Always check status** before important work
2. **Use dev mode** when testing ai changes
3. **Exit dev mode** when done testing
4. **Dev data persists** - you can `/ai-dev:dev on` later and continue
