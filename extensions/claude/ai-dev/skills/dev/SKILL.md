---
name: dev
description: Toggle development mode - isolates test environment from production data. Use when testing ai changes or experimenting safely.
argument-hint: "[on|off|status]"
allowed-tools: Bash, Read, Write
---

# /ai-dev:dev

Toggle between development/test environment and normal use.

## Quick Start

```bash
/ai-dev:dev on       # Enter dev mode (uses test environment)
/ai-dev:dev off      # Exit dev mode (uses normal environment)
/ai-dev:dev status   # Check current mode
```

## What Dev Mode Does

When **ON**:
- All ai operations use `.agentic-inquiry/dev/` environment
- Memories, index, and knowledge are isolated from production
- Banner displays each turn: `[ai DEV MODE]`
- Safe to experiment without polluting real data

When **OFF**:
- Normal ai operations use default environment
- No banner displayed
- Production data is used

## Implementation

Dev mode is tracked via `.agentic-inquiry/.dev-mode` file:
- File exists = dev mode ON
- File absent = dev mode OFF

Environment switching:
```bash
# Dev mode ON
export AI_CONFIG=.agentic-inquiry/dev/config.yaml
export AI_PROJECT_ID=ai-dev

# Dev mode OFF
unset AI_CONFIG  # uses default
export AI_PROJECT_ID=default
```

## Banner

When dev mode is active, a UserPromptSubmit hook displays:
```
[ai DEV MODE] Using test environment. `/ai-dev:dev off` to exit.
```
